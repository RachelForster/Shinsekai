from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, TypedDict

try:
    from typing import NotRequired
except ImportError:  # Python 3.10
    from typing_extensions import NotRequired


class RuntimeDependencyError(TypedDict):
    kind: Literal["missing_dependency"]
    message: str
    moduleName: str
    packageName: str
    logPath: NotRequired[str]


class HttpClientError(TypedDict):
    kind: Literal["http_client"]
    message: str
    errorType: str
    timeout: bool
    statusCode: int | None
    url: str
    reason: NotRequired[str]


class DownloadError(TypedDict):
    kind: Literal["download"]
    message: str
    errorType: str
    timeout: bool
    statusCode: int | None
    url: str
    source: str
    userMessage: str


class ProgressSnapshot(TypedDict):
    id: str
    kind: str
    title: str
    phase: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    message: str
    progress: float | None
    logs: list[str]
    error: NotRequired[str]
    errorCode: NotRequired[str]
    errorUserMessage: NotRequired[str]
    httpStatus: NotRequired[int | None]
    notice: NotRequired[str]
    noticeKind: NotRequired[Literal["error", "info", "warning"]]


ExceptionInfo = RuntimeDependencyError | HttpClientError | DownloadError


_NO_MODULE_PATTERNS = (
    re.compile(r"(?:ModuleNotFoundError|ImportError):\s+No module named ['\"]([^'\"]+)['\"]"),
    re.compile(r"No module named ['\"]([^'\"]+)['\"]"),
)

MODULE_PACKAGE_MAP = {
    "PIL": "Pillow",
    "anthropic": "anthropic",
    "cv2": "opencv-python",
    "fastembed": "fastembed",
    "google": "google-genai",
    "google.genai": "google-genai",
    "mem0": "mem0ai[extras]",
    "numpy": "numpy",
    "openai": "openai",
    "opencc": "opencc-python-reimplemented",
    "pandas": "pandas",
    "pygame": "pygame",
    "PySide6": "PySide6",
    "requests": "requests",
    "sentence_transformers": "sentence-transformers",
    "socksio": "socksio",
    "tiktoken": "tiktoken",
    "yaml": "PyYAML",
}


def missing_module_from_text(text: str) -> str | None:
    for pattern in _NO_MODULE_PATTERNS:
        match = pattern.search(text or "")
        if match:
            module_name = match.group(1).strip()
            return module_name or None
    return None


def missing_module_from_exception(exc: BaseException) -> str | None:
    if isinstance(exc, ModuleNotFoundError):
        module_name = getattr(exc, "name", None)
        if isinstance(module_name, str) and module_name.strip():
            return module_name.strip()
    return missing_module_from_text(str(exc))


def package_for_module(module_name: str) -> str:
    module_name = (module_name or "").strip()
    if module_name in MODULE_PACKAGE_MAP:
        return MODULE_PACKAGE_MAP[module_name]
    top_level = module_name.split(".", 1)[0]
    return MODULE_PACKAGE_MAP.get(top_level, top_level or module_name)


def runtime_dependency_error_from_text(
    text: str,
    *,
    log_path: str | Path | None = None,
) -> RuntimeDependencyError | None:
    module_name = missing_module_from_text(text)
    if not module_name:
        return None
    return runtime_dependency_error_from_module(module_name, log_path=log_path)


def runtime_dependency_error_from_exception(
    exc: BaseException,
    *,
    log_path: str | Path | None = None,
) -> RuntimeDependencyError | None:
    module_name = missing_module_from_exception(exc)
    if not module_name:
        return None
    return runtime_dependency_error_from_module(module_name, log_path=log_path)


def runtime_dependency_error_from_module(
    module_name: str,
    *,
    log_path: str | Path | None = None,
) -> RuntimeDependencyError:
    module_name = (module_name or "").strip()
    package_name = package_for_module(module_name)
    error: RuntimeDependencyError = {
        "kind": "missing_dependency",
        "message": f"Missing Python module: {module_name}",
        "moduleName": module_name,
        "packageName": package_name,
    }
    if log_path:
        error["logPath"] = str(log_path)
    return error


_HTTP_CLIENT_ERROR_NAMES = {
    "APIConnectionError",
    "APIError",
    "APIResponseValidationError",
    "APIStatusError",
    "APITimeoutError",
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "InternalServerError",
    "NotFoundError",
    "PermissionDeniedError",
    "RateLimitError",
    "UnprocessableEntityError",
}

HTTP_REASON_UNPAIRED_TOOL_MESSAGES = "unpaired_tool_messages"

_UNPAIRED_TOOL_MESSAGE_MARKERS = (
    "messages with role 'tool' must be a response to a preceding message with 'tool_calls'",
    "an assistant message with 'tool_calls' must be followed by tool messages",
    "tool_call_ids did not have response messages",
)


def _module_is(module_name: str, package: str) -> bool:
    return module_name == package or module_name.startswith(f"{package}.")


def _is_http_client_exception(exc: BaseException) -> bool:
    module_name = type(exc).__module__
    if _module_is(module_name, "httpx") or _module_is(module_name, "httpcore"):
        return True
    if _module_is(module_name, "urllib.error") and type(exc).__name__ in {"HTTPError", "URLError"}:
        return True
    if any(getattr(exc, attr, None) is not None for attr in ("status_code", "url")):
        return True
    if not (_module_is(module_name, "openai") or _module_is(module_name, "anthropic")):
        return False

    error_type = type(exc).__name__
    if error_type in _HTTP_CLIENT_ERROR_NAMES:
        return True
    if "timeout" in error_type.lower() or "connection" in error_type.lower():
        return True
    return any(
        getattr(exc, attr, None) is not None
        for attr in ("request", "response", "status_code")
    )


def _httpx_url(exc: BaseException) -> str:
    direct_url = getattr(exc, "url", None)
    if direct_url is not None:
        return str(direct_url)
    for owner in (exc, getattr(exc, "response", None)):
        request = getattr(owner, "request", None)
        url = getattr(request, "url", None)
        if url is not None:
            return str(url)
    return ""


def _httpx_status_code(exc: BaseException) -> int | None:
    direct_status_code = getattr(exc, "status_code", None)
    if isinstance(direct_status_code, int):
        return direct_status_code
    direct_code = getattr(exc, "code", None)
    if isinstance(direct_code, int):
        return direct_code
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


def http_client_error_from_exception(exc: BaseException) -> HttpClientError | None:
    if not _is_http_client_exception(exc):
        return None

    error_type = type(exc).__name__
    lowered_message = str(exc).lower()
    timeout = "timeout" in error_type.lower() or "timed out" in lowered_message or error_type in {
        "ConnectTimeout",
        "PoolTimeout",
        "ReadTimeout",
        "TimeoutException",
        "WriteTimeout",
    }
    message = str(exc).strip() or error_type
    error: HttpClientError = {
        "kind": "http_client",
        "message": f"HTTP request failed: {message}",
        "errorType": error_type,
        "timeout": timeout,
        "statusCode": _httpx_status_code(exc),
        "url": _httpx_url(exc),
    }
    if is_unpaired_tool_messages_error(exc, status_code=error["statusCode"]):
        error["reason"] = HTTP_REASON_UNPAIRED_TOOL_MESSAGES
    return error


def _download_user_message(error_type: str, message: str, status_code: int | None, timeout: bool) -> str:
    if status_code == 401:
        return "下载失败：认证失效或缺少访问令牌，请检查 Hugging Face token / 网络代理后重试。"
    if status_code == 403:
        return "下载失败：没有权限访问该资源，可能需要登录、申请模型权限，或切换可访问的镜像源。"
    if status_code == 404:
        return "下载失败：资源不存在或模型名称不正确，请检查下载地址。"
    if status_code == 429:
        return "下载失败：请求过于频繁或被限流，请稍后重试。"
    if timeout:
        return "下载超时：请检查网络、代理或镜像源设置，然后重试。"
    lowered = f"{error_type} {message}".lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "下载超时：请检查网络、代理或镜像源设置，然后重试。"
    if "proxy" in lowered:
        return "下载失败：代理连接异常，请检查系统代理或 Shinsekai 网络代理设置。"
    if "ssl" in lowered or "certificate" in lowered:
        return "下载失败：SSL 证书校验失败，请检查网络代理、证书或镜像源。"
    if status_code is not None:
        return f"下载失败：服务器返回 HTTP {status_code}，请检查网络、权限或镜像源。"
    return "下载失败：请检查网络、代理、镜像源或稍后重试。"


def download_error_from_exception(
    exc: BaseException,
    *,
    source: str = "",
    url: str = "",
) -> DownloadError:
    http_error = http_client_error_from_exception(exc)
    if http_error is not None:
        status_code = http_error.get("statusCode")
        timeout = http_error.get("timeout", False)
        error_url = url or http_error.get("url", "")
        error_type = http_error.get("errorType") or type(exc).__name__
        message = http_error.get("message") or str(exc).strip() or error_type
    else:
        status_code = _httpx_status_code(exc)
        error_text = str(exc).lower()
        error_type = type(exc).__name__
        error_type_lower = error_type.lower()
        timeout = "timeout" in error_type_lower or "timed out" in error_text
        error_url = url or _httpx_url(exc)
        message = str(exc).strip() or error_type

    return {
        "kind": "download",
        "message": f"Download failed: {message}",
        "errorType": error_type,
        "timeout": timeout,
        "statusCode": status_code,
        "url": error_url,
        "source": source,
        "userMessage": _download_user_message(error_type, message, status_code, timeout),
    }


def is_unpaired_tool_messages_error(
    exc: BaseException,
    *,
    status_code: int | None = None,
) -> bool:
    if status_code not in (400, 422, None):
        return False
    text = str(exc).lower()
    return any(marker in text for marker in _UNPAIRED_TOOL_MESSAGE_MARKERS)


def classify_exception(exc: BaseException) -> ExceptionInfo | None:
    dependency_error = runtime_dependency_error_from_exception(exc)
    if dependency_error:
        return dependency_error
    http_error = http_client_error_from_exception(exc)
    if http_error:
        return http_error
    return None
