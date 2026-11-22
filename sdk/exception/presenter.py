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
    from i18n import tr

    if status_code == 402 or _contains_any_keyword(raw_message, _LLM_BALANCE_KEYWORDS):
        return tr("presenter.llm.insufficient_balance")
    if status_code == 401 or _contains_any_keyword(raw_message, _LLM_AUTH_KEYWORDS):
        return tr("presenter.llm.unauthorized")
    if status_code == 403:
        return tr("presenter.llm.forbidden")
    if status_code == 429:
        return tr("presenter.llm.rate_limited")
    if timeout:
        return tr("presenter.llm.timeout")
    if status_code is not None and 500 <= status_code <= 599:
        return tr("presenter.llm.server_error", status_code=status_code)
    if status_code == 400:
        return tr("presenter.llm.bad_request")
    if status_code is not None:
        return tr("presenter.llm.http_failed", status_code=status_code)
    return tr("presenter.llm.network_failed")


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
        from i18n import tr

        return tr(
            "presenter.llm.missing_dependency",
            module_name=error_info["moduleName"],
            package_name=error_info["packageName"],
        )

    return f"{fallback_message}\n{exc}"
