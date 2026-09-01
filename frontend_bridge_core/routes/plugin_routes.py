from __future__ import annotations

from http import HTTPStatus
from urllib.parse import quote

from application.plugins.catalog import (
    _plugin_registry_rows,
    _plugin_rows,
    _set_plugin_enabled,
    _uninstall_plugin,
)
from application.plugins.install_plugin import install_plugin
from application.plugins.update_application import (
    get_application_update_info,
    list_application_update_tags,
    list_plugin_repository_tags,
    update_application,
)
from application.runtime.state import plugin_load_snapshot
from application.runtime.tasks import _is_running_task
from frontend_bridge_core.plugin_publisher import (
    _build_plugin_submission_issue_url,
    _copy_plugin_submission_json,
    _scan_local_plugin,
    _validate_plugin_submission,
)
from frontend_bridge_core.plugin_install import BridgePluginInstallProgress
from frontend_bridge_core.plugin_ui import (
    _frontend_chat_ui_contribution_payloads,
    _plugin_ui_detail,
    _run_frontend_chat_ui_contribution,
    _run_plugin_ui_action,
    _save_plugin_ui_config,
)
from frontend_bridge_core.routes.router import (
    ApiRequest,
    BodyKind,
    JsonResponse,
    Route,
    TaskResponse,
)

_BRIDGE_AUTH_QUERY = "shinsekai_bridge_token"


def inject_bridge_token(state, detail: dict) -> dict:
    token = str(getattr(state, "auth_token", "") or "").strip()
    if not token:
        return detail
    for page in detail.get("pages") or []:
        url = str(page.get("frontendUrl") or "")
        if url.startswith("/api/") and _BRIDGE_AUTH_QUERY not in url:
            separator = "&" if "?" in url else "?"
            page["frontendUrl"] = (
                f"{url}{separator}{_BRIDGE_AUTH_QUERY}={quote(token, safe='')}"
            )
    return detail


def _list_plugins(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_plugin_rows(plugin_load_snapshot(request.state)))


def _list_chat_ui_contributions(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_frontend_chat_ui_contribution_payloads())


def _plugin_status(request: ApiRequest) -> JsonResponse:
    return JsonResponse(plugin_load_snapshot(request.state))


def _plugin_ui(request: ApiRequest) -> JsonResponse:
    detail = _plugin_ui_detail(request.params["plugin_id"])
    return JsonResponse(inject_bridge_token(request.state, detail))


def _get_app_update_info(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(get_application_update_info())


def _get_plugin_registry(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(_plugin_registry_rows())


def _install_plugin(request: ApiRequest) -> JsonResponse | TaskResponse:
    plugin_id = str(request.body.get("source") or request.body.get("id") or "").strip()
    if not plugin_id:
        raise ValueError("plugin id is required")
    ref_kind = str(request.body.get("refKind") or "latest").strip()
    tag_name = str(request.body.get("tagName") or "").strip()
    overwrite = bool(request.body.get("overwrite"))
    with request.state.task_lock:
        running = [
            dict(task)
            for task in request.state.tasks.values()
            if task.get("kind") == "plugin-install"
            and task.get("source") == plugin_id
            and _is_running_task(task)
        ]
    if running:
        return JsonResponse(running[0], HTTPStatus.ACCEPTED)
    return TaskResponse(
        kind="plugin-install",
        title=f"安装插件 {plugin_id}",
        message="插件安装任务已排队。",
        task_updates={"source": plugin_id},
        worker=lambda task_id: install_plugin(
            BridgePluginInstallProgress(request.state, task_id),
            plugin_id,
            ref_kind=ref_kind,
            tag_name=tag_name,
            overwrite=overwrite,
        ),
    )


def _get_repo_tags(request: ApiRequest) -> JsonResponse:
    return JsonResponse(list_plugin_repository_tags(request.body))


def _scan_plugin(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_scan_local_plugin(request.body))


def _validate_plugin(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_validate_plugin_submission(request.body))


def _build_issue_url(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_build_plugin_submission_issue_url(request.body))


def _copy_submission_json(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_copy_plugin_submission_json(request.body))


def _get_app_update_tags(_request: ApiRequest) -> JsonResponse:
    return JsonResponse(list_application_update_tags())


def _run_app_update_route(request: ApiRequest) -> TaskResponse:
    ref_kind = str(request.body.get("refKind") or "latest").strip()
    tag_name = str(request.body.get("tagName") or "").strip()
    return TaskResponse(
        kind="app-update",
        title="更新主程序",
        message="主程序更新任务已排队。",
        task_updates={"refKind": ref_kind, "tagName": tag_name},
        worker=lambda task_id: update_application(
            request.state,
            task_id,
            request.body,
        ),
    )


def _set_enabled(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _set_plugin_enabled(
            request.params["plugin_id"],
            bool(request.body.get("enabled")),
        )
    )


def _run_chat_ui_contribution(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _run_frontend_chat_ui_contribution(
            request.params["plugin_id"],
            request.params["contribution_id"],
        )
    )


def _run_ui_action(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _run_plugin_ui_action(
            request.params["plugin_id"],
            request.params["page_id"],
            request.params["action_id"],
            request.body,
        )
    )


def _save_ui_config(request: ApiRequest) -> JsonResponse:
    return JsonResponse(
        _save_plugin_ui_config(
            request.params["plugin_id"],
            request.params["page_id"],
            request.body,
        )
    )


def _delete_plugin(request: ApiRequest) -> JsonResponse:
    return JsonResponse(_uninstall_plugin(request.params["plugin_id"]))


PLUGIN_ROUTES = (
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/plugins",
        handler=_list_plugins,
        body_kind=BodyKind.NONE,
        name="plugins.list",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/plugins/chat-ui-contributions",
        handler=_list_chat_ui_contributions,
        body_kind=BodyKind.NONE,
        name="plugins.chat_ui_contributions",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/plugins/status",
        handler=_plugin_status,
        body_kind=BodyKind.NONE,
        name="plugins.status",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/plugins/{plugin_id}/ui",
        handler=_plugin_ui,
        body_kind=BodyKind.NONE,
        name="plugins.ui",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/plugins/app-update/info",
        handler=_get_app_update_info,
        body_kind=BodyKind.NONE,
        name="plugins.app_update.info",
    ),
    Route(
        methods=frozenset({"GET"}),
        pattern="/api/plugins/registry",
        handler=_get_plugin_registry,
        body_kind=BodyKind.NONE,
        name="plugins.registry",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/install",
        handler=_install_plugin,
        name="plugins.install",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/repo-tags",
        handler=_get_repo_tags,
        name="plugins.repo_tags",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/publisher/scan",
        handler=_scan_plugin,
        name="plugins.publisher.scan",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/publisher/validate",
        handler=_validate_plugin,
        name="plugins.publisher.validate",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/publisher/issue-url",
        handler=_build_issue_url,
        name="plugins.publisher.issue_url",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/publisher/copy-json",
        handler=_copy_submission_json,
        name="plugins.publisher.copy_json",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/app-update/tags",
        handler=_get_app_update_tags,
        name="plugins.app_update.tags",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/app-update/run",
        handler=_run_app_update_route,
        name="plugins.app_update.run",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/{plugin_id}/enabled",
        handler=_set_enabled,
        name="plugins.enabled",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/{plugin_id}/chat-ui/{contribution_id}/run",
        handler=_run_chat_ui_contribution,
        name="plugins.chat_ui.run",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/{plugin_id}/ui/{page_id}/actions/{action_id}",
        handler=_run_ui_action,
        name="plugins.ui.actions.run",
    ),
    Route(
        methods=frozenset({"POST"}),
        pattern="/api/plugins/{plugin_id}/ui/{page_id}/config",
        handler=_save_ui_config,
        name="plugins.ui.config.save",
    ),
    Route(
        methods=frozenset({"DELETE"}),
        pattern="/api/plugins/{plugin_id}",
        handler=_delete_plugin,
        body_kind=BodyKind.NONE,
        name="plugins.delete",
    ),
)
