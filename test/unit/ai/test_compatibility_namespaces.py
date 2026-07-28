from __future__ import annotations


def test_legacy_ai_modules_alias_canonical_implementations() -> None:
    from ai.asr import asr_adapter, asr_manager, streaming_controller
    from ai.llm import llm_adapter, llm_manager, template_generator
    from ai.t2i import t2i_adapter, t2i_manager
    from ai.tools import memory_tools, tool_manager
    from ai.tts import tts_adapter, tts_manager
    from asr import asr_adapter as legacy_asr_adapter
    from asr import asr_manager as legacy_asr_manager
    from asr import streaming_controller as legacy_streaming_controller
    from llm import llm_adapter as legacy_llm_adapter
    from llm import llm_manager as legacy_llm_manager
    from llm import template_generator as legacy_template_generator
    from llm.tools import memory_tools as legacy_memory_tools
    from llm.tools import tool_manager as legacy_tool_manager
    from t2i import t2i_adapter as legacy_t2i_adapter
    from t2i import t2i_manager as legacy_t2i_manager
    from tts import tts_adapter as legacy_tts_adapter
    from tts import tts_manager as legacy_tts_manager

    assert legacy_asr_adapter is asr_adapter
    assert legacy_asr_manager is asr_manager
    assert legacy_streaming_controller is streaming_controller
    assert legacy_llm_adapter is llm_adapter
    assert legacy_llm_manager is llm_manager
    assert legacy_template_generator is template_generator
    assert legacy_memory_tools is memory_tools
    assert legacy_tool_manager is tool_manager
    assert legacy_t2i_adapter is t2i_adapter
    assert legacy_t2i_manager is t2i_manager
    assert legacy_tts_adapter is tts_adapter
    assert legacy_tts_manager is tts_manager


def test_mcp_config_compatibility_paths_alias_config_layer() -> None:
    from ai.tools import mcp_config_file
    from config import mcp_config
    from llm.tools import mcp_config_file as legacy_mcp_config_file

    assert mcp_config_file is mcp_config
    assert legacy_mcp_config_file is mcp_config
