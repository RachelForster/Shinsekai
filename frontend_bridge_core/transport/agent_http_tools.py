"""Host-owned Agent tools backed by the existing bridge HTTP API."""

from __future__ import annotations

import http.client
import ipaddress
import json
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictStr, field_validator

from application.agent.execute_host_tool import AgentHostTool
from sdk.agent import AgentEffect, AgentError, AgentHostToolCall, AgentHostToolResult
from sdk.logging.redaction import REDACTED, redact_text


@dataclass(frozen=True)
class _Api:
    method: str
    path: str
    description: str


READ_APIS = {
    "app.status": _Api("GET", "/api/health", "应用及插件加载状态"),
    "app.config": _Api("GET", "/api/config", "当前配置，凭据会脱敏"),
    "characters.list": _Api("GET", "/api/characters", "人物及已有资源配置"),
    "plugins.list": _Api("GET", "/api/plugins", "已安装插件"),
    "plugins.status": _Api("GET", "/api/plugins/status", "插件加载状态"),
    "plugins.registry": _Api("GET", "/api/plugins/registry", "可安装插件目录"),
    "plugins.inspect": _Api(
        "GET",
        "/api/plugins/{plugin_id}/ui",
        "params.plugin_id；返回配置页面、schema、动作",
    ),
    "tasks.get": _Api(
        "GET", "/api/tasks/{task_id}", "params.task_id；任务状态、进度和结果"
    ),
    "logs.list": _Api("GET", "/api/logs", "可读取的日志文件"),
    "logs.read": _Api("POST", "/api/logs/read", "body.path；读取日志，凭据会脱敏"),
    "files.browse": _Api(
        "POST", "/api/files/browse", "body.path 为目录；可选 body.showHidden"
    ),
    "tts.environment": _Api(
        "GET",
        "/api/config/tts-bundle/recommendation",
        "GPU 与推理环境推荐；不代表训练资格",
    ),
}
WRITE_APIS = {
    "characters.save": _Api(
        "POST",
        "/api/characters",
        "body.character 为完整人物配置；编辑时提供 body.originalName",
    ),
    "characters.sprites.import": _Api(
        "POST",
        "/api/characters/sprites/upload",
        "body.name、body.paths（已存在的图片路径列表）",
    ),
    "plugins.install": _Api(
        "POST", "/api/plugins/install", "body.source 为目录中的插件来源；返回安装任务"
    ),
    "plugins.enable": _Api(
        "POST",
        "/api/plugins/{plugin_id}/enabled",
        "params.plugin_id；body.enabled 为 boolean",
    ),
    "plugins.configure": _Api(
        "POST",
        "/api/plugins/{plugin_id}/ui/{page_id}/config",
        "params.plugin_id、page_id；body.values 按 plugins.inspect 返回的 schema 填写",
    ),
    "plugins.action": _Api(
        "POST",
        "/api/plugins/{plugin_id}/ui/{page_id}/actions/{action_id}",
        "params.plugin_id、page_id、action_id；body.values 按插件动作要求填写",
    ),
    "tasks.cancel": _Api(
        "POST", "/api/tasks/{task_id}/cancel", "params.task_id；请求取消 bridge 任务"
    ),
    "tts.install": _Api(
        "POST",
        "/api/config/tts-bundle/download",
        "body.kind 为 genie、gptso 或 gptso50；返回下载任务",
    ),
}


def _operations(apis: dict[str, _Api]) -> str:
    return "；".join(f"{name}: {api.description}" for name, api in apis.items())


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    params: dict[str, StrictStr] = Field(
        default_factory=dict, description="仅填路径参数"
    )
    body: dict[str, JsonValue] = Field(
        default_factory=dict, description="原 HTTP API 的 JSON 请求体"
    )


class BridgeReadInput(_Arguments):
    operation: StrictStr = Field(
        description=_operations(READ_APIS), json_schema_extra={"enum": list(READ_APIS)}
    )

    @field_validator("operation")
    @classmethod
    def registered_operation(cls, value):
        if value not in READ_APIS:
            raise ValueError("Unknown bridge read operation")
        return value


class BridgeWriteInput(_Arguments):
    operation: StrictStr = Field(
        description=_operations(WRITE_APIS),
        json_schema_extra={"enum": list(WRITE_APIS)},
    )

    @field_validator("operation")
    @classmethod
    def registered_operation(cls, value):
        if value not in WRITE_APIS:
            raise ValueError("Unknown bridge write operation")
        return value


class BridgeApiOutput(BaseModel):
    httpStatus: int
    data: JsonValue
    taskId: str | None = None
    accepted: bool = False


_SENSITIVE = re.compile(
    r"api[_-]?key|authorization|credential|password|secret|cookie|(?:^|[_-])token(?:$|[_-])",
    re.IGNORECASE,
)


def _sensitive(key: str) -> bool:
    key = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", key)
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return bool(_SENSITIVE.search(key))


def _redact(value: JsonValue, token: str) -> JsonValue:
    secrets = {token}

    def collect(item, sensitive=False):
        if isinstance(item, dict):
            for key, child in item.items():
                collect(child, sensitive or _sensitive(key))
        elif isinstance(item, list):
            for child in item:
                collect(child, sensitive)
        elif sensitive and isinstance(item, str) and len(item) >= 4:
            secrets.add(item)

    collect(value)
    ordered_secrets = sorted(secrets, key=len, reverse=True)

    def clean(item):
        if isinstance(item, dict):
            return {
                key: REDACTED if _sensitive(key) else clean(child)
                for key, child in item.items()
            }
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, str):
            for secret in ordered_secrets:
                item = item.replace(secret, REDACTED)
            return redact_text(item)
        return item

    return clean(value)


def _invalid_json_constant(value):
    raise ValueError("Invalid JSON number")


class _ApiError(Exception):
    def __init__(
        self, code: str, message: str, state: Literal["not_applied", "unknown"]
    ):
        self.code, self.message, self.state = code, message, state


class BridgeHttpClient:
    """Address and credentials come from the bound server, never model arguments."""

    MAX_RESPONSE_BYTES = 512 * 1024

    def __init__(self, host: str, port: int, token: str, *, timeout: float = 30):
        address = ipaddress.ip_address(host)
        self.host = str(
            ipaddress.ip_address("::1" if address.version == 6 else "127.0.0.1")
            if address.is_unspecified
            else address
        )
        if not 0 < port < 65536 or not token.strip() or timeout <= 0:
            raise ValueError("Invalid bridge HTTP configuration")
        self.port, self._token, self.timeout = port, token, timeout

    def request(self, api: _Api, arguments: _Arguments) -> BridgeApiOutput:
        fields = set(re.findall(r"\{([^}]+)\}", api.path))
        if set(arguments.params) != fields or any(
            not value for value in arguments.params.values()
        ):
            raise _ApiError(
                "INVALID_REQUEST",
                "Bridge path parameters do not match the operation",
                "not_applied",
            )
        if api.method == "GET" and arguments.body:
            raise _ApiError(
                "INVALID_REQUEST", "GET operations do not accept a body", "not_applied"
            )
        path = api.path.format(
            **{key: quote(value, safe="") for key, value in arguments.params.items()}
        )
        body = (
            None
            if api.method == "GET"
            else json.dumps(arguments.body, ensure_ascii=False, allow_nan=False).encode(
                "utf-8"
            )
        )
        connection = http.client.HTTPConnection(
            self.host, self.port, timeout=self.timeout
        )
        try:
            # HTTPConnection uses the fixed address directly, without environment proxies or redirects.
            connection.request(
                api.method,
                path,
                body,
                {
                    "Content-Type": "application/json",
                    "X-Shinsekai-Bridge-Token": self._token,
                },
            )
            response = connection.getresponse()
            raw = response.read(self.MAX_RESPONSE_BYTES + 1)
            if len(raw) > self.MAX_RESPONSE_BYTES:
                raise _ApiError(
                    "LIMIT_EXCEEDED",
                    "Bridge response exceeds the size limit",
                    "unknown",
                )
            try:
                payload = _redact(
                    json.loads(raw, parse_constant=_invalid_json_constant), self._token
                )
            except (ValueError, UnicodeError, RecursionError):
                raise _ApiError(
                    "PROTOCOL_MISMATCH", "Bridge returned invalid JSON", "unknown"
                ) from None
            if not 200 <= response.status < 300:
                message = (
                    str(payload.get("error", "")) if isinstance(payload, dict) else ""
                )
                code = (
                    "AUTH_REQUIRED"
                    if response.status == 401
                    else "TOOL_DENIED" if response.status == 403 else "INVALID_REQUEST"
                )
                raise _ApiError(
                    code, f"Bridge HTTP {response.status}: {message[:2000]}", "unknown"
                )
            if isinstance(payload, dict) and payload.get("error"):
                raise _ApiError(
                    "INVALID_REQUEST", str(payload["error"])[:2000], "unknown"
                )
            if (
                len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                > self.MAX_RESPONSE_BYTES
            ):
                raise _ApiError(
                    "LIMIT_EXCEEDED",
                    "Sanitized bridge response exceeds the size limit",
                    "unknown",
                )
            accepted = response.status == 202
            return BridgeApiOutput(
                httpStatus=response.status,
                data=payload,
                accepted=accepted,
                taskId=(
                    str(payload["id"])
                    if accepted and isinstance(payload, dict) and payload.get("id")
                    else None
                ),
            )
        except (OSError, http.client.HTTPException):
            # A lost response can follow a committed write; do not retry it here.
            raise _ApiError(
                "BACKEND_UNAVAILABLE",
                "Bridge HTTP request failed; query state before retrying a write",
                "unknown",
            ) from None
        finally:
            connection.close()


def build_bridge_http_tools(
    host: str, port: int, token: str, *, timeout: float = 30
) -> tuple[AgentHostTool, ...]:
    client = BridgeHttpClient(host, port, token, timeout=timeout)

    def tool(name, apis, model, effect_kind):
        def execute(task, call: AgentHostToolCall):
            try:
                arguments = model.model_validate(call.arguments)
                result = client.request(apis[arguments.operation], arguments)
                effects = (
                    ()
                    if effect_kind == "read"
                    else (
                        AgentEffect(
                            call_id=call.call_id,
                            tool_name=call.name,
                            state="applied",
                            description=(
                                f"Bridge accepted task {result.taskId}; completion must be checked with tasks.get"
                                if result.accepted
                                else f"Bridge API {arguments.operation} returned successfully"
                            ),
                        ),
                    )
                )
                return AgentHostToolResult(
                    call_id=call.call_id,
                    ok=True,
                    data=result.model_dump(mode="json"),
                    effects=effects,
                )
            except _ApiError as exc:
                effects = (
                    ()
                    if effect_kind == "read"
                    else (
                        AgentEffect(
                            call_id=call.call_id,
                            tool_name=call.name,
                            state=exc.state,
                            description=exc.message,
                        ),
                    )
                )
                return AgentHostToolResult(
                    call_id=call.call_id,
                    ok=False,
                    error=AgentError(code=exc.code, message=exc.message),
                    effects=effects,
                )

        return AgentHostTool.from_models(
            name=name,
            description=(
                "调用 Shinsekai 已有的 bridge HTTP API。选 operation，params 填路径参数，body 填原 JSON 参数。"
                "先读取现有数据与插件 schema；accepted=true 只代表受理，使用 tasks.get 检查完成。"
            ),
            input_model=model,
            output_model=BridgeApiOutput,
            effect_kind=effect_kind,
            execute=execute,
        )

    return (
        tool("shinsekai.bridge.read", READ_APIS, BridgeReadInput, "read"),
        tool("shinsekai.bridge.write", WRITE_APIS, BridgeWriteInput, "execute"),
    )
