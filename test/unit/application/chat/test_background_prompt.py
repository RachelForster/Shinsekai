from types import SimpleNamespace

from ai.llm.template.prompts import UserPromptContext, build_user_prompt_section
from application.chat.background_prompt import current_background_context


def test_resolves_current_image_instead_of_initial_background(tmp_path):
    old = SimpleNamespace(name="旧校舍", sprites=[{"path": tmp_path / "old.png"}], bg_tags="1：旧教室")
    current = SimpleNamespace(
        name="街道",
        sprites=[{"path": tmp_path / "day.png"}, SimpleNamespace(path=tmp_path / "night.png")],
        bg_tags="1：白天街道\n2：雨夜街道",
    )
    runtime = SimpleNamespace(
        background=old,
        config=SimpleNamespace(config=SimpleNamespace(background_list=[old, current])),
        ui_update_manager=SimpleNamespace(current_background_path=str(tmp_path / "night.png").replace("/", "\\")),
    )
    assert current_background_context(runtime) == {
        "背景组": "街道", "背景编号": 2, "描述": "雨夜街道", "图片": "night.png",
    }

    runtime.ui_update_manager.current_background_path = tmp_path / "generated.png"
    assert current_background_context(runtime) == {"图片": "generated.png"}
    for path in (None, ""):
        runtime.ui_update_manager.current_background_path = path
        background = current_background_context(runtime)
        assert background is None
        context = UserPromptContext(user_input="用户原文", background=background)
        assert build_user_prompt_section().render(context) == "用户原文"
