from __future__ import annotations

from typing import Any

from ai.llm.llm_manager import LLMAdapterFactory, LLMManager


def generate_character_setting(
    character_manager: Any,
    name: str,
    setting: str,
) -> tuple[str, str]:
    """Generate and persist a character setting through the configured LLM."""

    if not name:
        return "请选择或输入要生成的角色的名字！", setting

    config_manager = character_manager._config_manager
    character = config_manager.get_character_by_name(name)
    if character is None:
        character_manager.add_character(
            name=name,
            color="",
            sprite_prefix="",
            gpt_model_path="",
            sovits_model_path="",
            refer_audio_path="",
            prompt_text="",
            prompt_lang="",
            character_setting=setting,
        )
        character = config_manager.get_character_by_name(name)
        if character is None:
            return f"创建角色 {name} 失败。", setting

    setting = "无" if not setting else setting
    template = f"""
    你需要帮助用户写出{name}的角色设定，包括{name}的背景信息，性格特点，和语言习惯。输出plain text格式，不要使用markdown格式。
    将{name}的背景信息，性格特点，和语言习惯分段写，并且同一段内标号，不一定是3点，有可能比3点多。
    输出格式示例：
    {name}的背景信息：
    1.姓名和出处：
    2.外表：
    3.背景：
    4.经历：

    {name}的性格特点：
    1.
    2.
    3.

    {name}的语言习惯：
    1.
    2.
    """

    try:
        llm_provider, llm_model, llm_base_url, api_key = (
            config_manager.get_llm_api_config()
        )
        if not llm_provider or not api_key or not llm_model:
            return (
                "LLM 配置不完整，请先设定大语言模型供应商、模型和 API Key。",
                setting,
            )

        factory_kwargs = config_manager.merged_llm_factory_kwargs(
            llm_provider,
            {
                "llm_provider": llm_provider,
                "api_key": api_key,
                "base_url": llm_base_url,
                "model": llm_model,
            },
        )
        signature = tuple(
            sorted((str(key), repr(value)) for key, value in factory_kwargs.items())
        )
        if (
            character_manager._llm_manager is None
            or character_manager._llm_config_signature != signature
        ):
            adapter = LLMAdapterFactory.create_adapter(**factory_kwargs)
            character_manager._llm_manager = LLMManager(
                adapter=adapter,
                user_template=template,
            )
            character_manager._llm_config_signature = signature

        character_manager._llm_manager.set_user_template(template)
        generated = character_manager._llm_manager.chat(
            f"补充信息：{setting},请输出结果：",
            stream=False,
            response_format={"type": "text"},
            include_local_time=False,
        )
        character.character_setting = generated
        config_manager.save_characters_config()
        return "输出成功", character.character_setting
    except ImportError:
        return (
            "输出失败: LLM 模块依赖未找到 (LLMAdapterFactory, LLMManager)",
            setting,
        )
    except Exception as exc:
        return f"输出失败:{exc}", setting
