from __future__ import annotations

from sdk.exception.types import classify_exception


_LLM_BALANCE_KEYWORDS = (
    "balance",
    "billing",
    "credit",
    "credits",
    "insufficient_quota",
    "insufficient quota",
    "insufficient balance",
    "no funds",
    "payment required",
    "quota exceeded",
    "余额",
    "额度",
    "欠费",
    "计费",
    "充值",
)

_LLM_AUTH_KEYWORDS = (
    "api key",
    "authentication",
    "invalid key",
    "invalid_api_key",
    "unauthorized",
    "未授权",
    "鉴权",
    "认证",
    "密钥",
)


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def llm_http_action_message(status_code: int | None, raw_message: str, *, timeout: bool) -> str:
    if status_code == 402 or _contains_any_keyword(raw_message, _LLM_BALANCE_KEYWORDS):
        return "LLM API 额度或余额不足：请到服务商控制台充值、开通计费，或更换有额度的 API Key。"
    if status_code == 401 or _contains_any_keyword(raw_message, _LLM_AUTH_KEYWORDS):
        return "LLM API 未授权：请检查 API Key 是否填写正确、是否过期，保存设置后重试。"
    if status_code == 403:
        return "LLM API 权限不足：请确认当前账号或 API Key 有访问该模型的权限，或切换到已授权模型。"
    if status_code == 429:
        return "LLM API 请求过于频繁或触发限额：请稍后重试、降低请求频率，或检查服务商限流/套餐。"
    if timeout:
        return "LLM API 请求超时：请检查网络、代理、Base URL，或稍后重试。"
    if status_code is not None and 500 <= status_code <= 599:
        return f"LLM API 服务商暂时异常：HTTP {status_code}。请稍后重试，或切换服务商/模型。"
    if status_code == 400:
        return "LLM API 请求参数有误：请检查模型名、Base URL、上下文长度和当前服务商支持的参数。"
    if status_code is not None:
        return f"LLM API 请求失败：HTTP {status_code}。请查看服务商错误信息并调整配置。"
    return "LLM API 网络请求失败：请检查网络、代理、Base URL 和服务商状态。"


def format_llm_exception_message(exc: BaseException, *, fallback_message: str) -> str:
    error_info = classify_exception(exc)
    if not error_info:
        return f"{fallback_message}\n{exc}"

    if error_info["kind"] == "http_client":
        message = llm_http_action_message(
            error_info["statusCode"],
            error_info["message"],
            timeout=error_info["timeout"],
        )
        if error_info["url"]:
            message += f"\nURL: {error_info['url']}"
        if error_info["statusCode"] is not None:
            message += f"\nHTTP status: {error_info['statusCode']}"
        message += f"\n{error_info['message']}"
        return message

    if error_info["kind"] == "missing_dependency":
        return (
            f"LLM 运行缺少 Python 模块：{error_info['moduleName']}\n"
            f"建议安装包：{error_info['packageName']}"
        )

    return f"{fallback_message}\n{exc}"
