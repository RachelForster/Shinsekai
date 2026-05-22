from core.runtime.ui_update_manager import format_context_token_estimate


def test_format_context_token_estimate_is_compact():
    text = format_context_token_estimate(
        {
            "system_prompt_tokens": 1200,
            "history_tokens": 34567,
            "tool_definition_tokens": 890,
            "estimated_total_tokens": 36657,
        }
    )

    assert text == "tokens sys 1.2k | hist 34.6k | tools 890 | total 36.7k"
