from __future__ import annotations


def test_bridge_compatibility_modules_alias_application_implementations() -> None:
    from application.chat import initialization, runtime_process, templates
    from application.model_assets import service, tts_bundle
    from application.plugins import catalog, updates
    from application.runtime import dependencies, state, tasks
    from frontend_bridge_core import (
        chat,
        chat_init,
        model_assets,
        plugin_catalog,
        plugin_updates,
        runtime_dependencies,
        state as bridge_state,
        tasks as bridge_tasks,
        templates as bridge_templates,
        tts,
    )

    assert chat is runtime_process
    assert chat_init is initialization
    assert model_assets is service
    assert plugin_catalog is catalog
    assert plugin_updates is updates
    assert runtime_dependencies is dependencies
    assert bridge_state is state
    assert bridge_tasks is tasks
    assert bridge_templates is templates
    assert tts is tts_bundle

    from frontend_bridge_core import handler
    from frontend_bridge_core.routes import api

    assert handler is api


def test_core_runtime_compatibility_modules_alias_application_runtime() -> None:
    from application.runtime import context, event_sink, shutdown, workflow
    from core.runtime import app_runtime
    from core.runtime import event_sink as legacy_event_sink
    from core.runtime import shutdown as legacy_shutdown
    from core.runtime import workflow as legacy_workflow

    assert app_runtime is context
    assert legacy_event_sink is event_sink
    assert legacy_shutdown is shutdown
    assert legacy_workflow is workflow
