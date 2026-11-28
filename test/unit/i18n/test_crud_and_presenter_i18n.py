from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import warnings

import pytest

from application.backgrounds import (
    BackgroundOperation,
    BackgroundUseCase,
    parse_background_request,
)
from application.characters import (
    CharacterOperation,
    CharacterUseCase,
    parse_character_request,
    validate_character_payload,
)
from config.background_manager import BackgroundManager
from config.background_ops import BackgroundProfileError, save_background_patch
from config.character_config import CharacterConfig
from config.character_manager import CharacterManager
from config.character_ops import (
    CharacterProfileError,
    delete_character_and_assets,
    save_character_patch,
)
from config.schema import Background, Character, SELF_PERSONA_NAME, SELF_PERSONA_SPRITE_PREFIX
from core.packaging.background_package import stage_background_package_import
from core.packaging.character_package import stage_character_package_import
from core.packaging.effect_package import stage_effect_package_import
from frontend_bridge_core.i18n_helpers import bind_bridge_state
from i18n import bind_language, init_i18n, is_operation_error_message
from sdk.exception.handler import _format_dialog_message
from sdk.exception.presenter import (
    format_llm_exception_message,
    llm_http_action_message,
)
from sdk.ui import validators


@pytest.fixture(autouse=True)
def _reset_locale_after_test():
    yield
    init_i18n("zh_CN")


def _make_bridge_state(tmp_path: Path, lang: str, *, backgrounds=None, characters=None):
    bg_list = list(backgrounds or [])
    char_list = list(characters or [])

    class _FakeConfigManager:
        def __init__(self) -> None:
            self.config = SimpleNamespace(
                system_config=SimpleNamespace(ui_language=lang),
                api_config=SimpleNamespace(tts_provider="none"),
                background_list=bg_list,
                characters=char_list,
            )

        def get_background_by_name(self, name: str):
            return next((bg for bg in self.config.background_list if bg.name == name), None)

        def get_character_by_name(self, name: str):
            return next((ch for ch in self.config.characters if ch.name == name), None)

        def save_background_config(self) -> None:
            pass

        def save_characters_config(self) -> None:
            pass

        def reload(self) -> None:
            pass

    cfg_mgr = _FakeConfigManager()
    bg_mgr = BackgroundManager.__new__(BackgroundManager)
    bg_mgr._config_manager = cfg_mgr
    char_mgr = CharacterManager.__new__(CharacterManager)
    char_mgr._config_manager = cfg_mgr

    return SimpleNamespace(
        config_manager=cfg_mgr,
        background_manager=bg_mgr,
        character_manager=char_mgr,
        project_root_dir=str(tmp_path),
        template_dir_path=str(tmp_path / "templates"),
    )


class _DummyBgTarget:
    def __init__(self, items: list[Background]) -> None:
        self._items = items

    def get_by_id(self, bg_id: str):
        return next((b for b in self._items if b.id == bg_id), None)

    def get_by_name(self, name: str):
        return next((b for b in self._items if b.name == name), None)

    def list_all(self):
        return list(self._items)

    def save_background(self, background: Background) -> None:
        pass

    def delete_background(self, background: Background) -> None:
        pass


class _DummyCharTarget:
    def __init__(self, items: list[Character]) -> None:
        self._items = items

    def get_by_id(self, char_id: str):
        return next((c for c in self._items if c.id == char_id), None)

    def get_by_name(self, name: str):
        return next((c for c in self._items if c.name == name), None)

    def list_all(self):
        return list(self._items)

    def save_character(self, character: Character) -> None:
        pass

    def delete_character(self, character: Character) -> None:
        pass

    def ensure_self_persona(self) -> Character:
        return self._items[0]


class TestBackgroundCrudI18n:
    @pytest.mark.parametrize(
        ("lang", "expected"),
        [
            ("zh_CN", "找不到背景组: Ghost"),
            ("en", "Background group not found: Ghost"),
            ("ja", "背景グループが見つかりません: Ghost"),
        ],
    )
    def test_background_use_case_missing_target_raises_localized_runtime_error(
        self, tmp_path: Path, lang: str, expected: str
    ) -> None:
        state = _make_bridge_state(tmp_path, lang)
        use_case = BackgroundUseCase(state, file_access_roots=(tmp_path,))
        img = tmp_path / "bg.png"
        img.write_bytes(b"png")

        with bind_bridge_state(state):
            with pytest.raises(RuntimeError, match=expected):
                use_case.execute(
                    parse_background_request(BackgroundOperation.DELETE, {"name": "Ghost"})
                )
            with pytest.raises(RuntimeError, match=expected):
                use_case.execute(
                    parse_background_request(
                        BackgroundOperation.UPLOAD_IMAGES,
                        {"name": "Ghost", "paths": [str(img)]},
                    )
                )

    @pytest.mark.parametrize(
        ("lang", "expected_empty", "expected_dup"),
        [
            ("zh_CN", "名称不能为空！", "已与其他背景组重复"),
            ("en", "Name cannot be empty!", 'Background group name "School" already exists!'),
            ("ja", "名前を入力してください！", "背景グループ名「School」はすでに他の背景グループと重複しています！"),
        ],
    )
    def test_save_background_patch_validation_errors(
        self, lang: str, expected_empty: str, expected_dup: str
    ) -> None:
        target = _DummyBgTarget(
            [
                Background(name="Room", sprite_prefix="room"),
                Background(name="School", sprite_prefix="school"),
            ]
        )
        with bind_language(lang):
            with pytest.raises(BackgroundProfileError) as exc_empty:
                save_background_patch(target, {"name": "   "})
            assert expected_empty in str(exc_empty.value)

            with pytest.raises(BackgroundProfileError) as exc_dup:
                save_background_patch(target, {"name": "School"}, original_name="Room")
            assert expected_dup in str(exc_dup.value)


class TestCharacterCrudI18n:
    @pytest.mark.parametrize(
        ("lang", "expected_gpt_label", "expected_ascii"),
        [
            ("zh_CN", "GPT 模型路径", "只能包含英文字母"),
            ("en", "GPT model path", "must contain only ASCII letters"),
            ("ja", "GPT モデルパス", "半角英数字と半角記号のみ"),
        ],
    )
    def test_validate_character_payload_localized_labels_and_reasons(
        self,
        tmp_path: Path,
        lang: str,
        expected_gpt_label: str,
        expected_ascii: str,
    ) -> None:
        state = _make_bridge_state(tmp_path, lang)
        payload = {
            "name": "Mika",
            "color": "#ffffff",
            "sprite_prefix": "中文目录",
            "gpt_model_path": "/kaggle/input/bad.pth",
            "sovits_model_path": "/kaggle/input/ok.pth",
            "refer_audio_path": "/kaggle/input/ref.wav",
        }
        with bind_bridge_state(state):
            with pytest.raises(ValueError) as exc_info:
                validate_character_payload(payload, allow_remote_voice_paths=True)
            msg = str(exc_info.value)
            assert expected_gpt_label in msg
            assert expected_ascii in msg

    @pytest.mark.parametrize(
        ("lang", "expected"),
        [
            ("zh_CN", "找不到角色: MissingHero"),
            ("en", "Character not found: MissingHero"),
            ("ja", "キャラクターが見つかりません: MissingHero"),
        ],
    )
    def test_character_use_case_missing_target_raises_localized_runtime_error(
        self, tmp_path: Path, lang: str, expected: str
    ) -> None:
        state = _make_bridge_state(tmp_path, lang)
        use_case = CharacterUseCase(state, file_access_roots=(tmp_path,))
        img = tmp_path / "sprite.png"
        img.write_bytes(b"png")

        with bind_bridge_state(state):
            del_res = use_case.execute(
                parse_character_request(CharacterOperation.DELETE, {"name": "MissingHero"})
            )
            assert del_res == {"message": expected, "names": []}

            with pytest.raises(RuntimeError, match=expected):
                use_case.execute(
                    parse_character_request(
                        CharacterOperation.UPLOAD_SPRITES,
                        {"name": "MissingHero", "paths": [str(img)]},
                    )
                )
            with pytest.raises(RuntimeError, match=expected):
                use_case.execute(
                    parse_character_request(
                        CharacterOperation.DELETE_ALL_SPRITES,
                        {"name": "MissingHero"},
                    )
                )

    @pytest.mark.parametrize(
        ("lang", "expected_into_self", "expected_prefix_lock", "expected_delete"),
        [
            (
                "zh_CN",
                "不能将其他角色重命名为「自设」！",
                "内置自设人物的立绘目录名固定为「__self__」，不可修改！",
                "内置「自设」人物不可删除！",
            ),
            (
                "en",
                'Cannot rename another character to "自设" (Self)!',
                'The built-in persona\'s sprite directory is locked to "__self__" and cannot be changed!',
                "The built-in Self character cannot be deleted!",
            ),
            (
                "ja",
                "他のキャラクターを「自设」にリネームすることはできません！",
                "組み込み自設キャラクターの立ち絵ディレクトリは「__self__」に固定されており、変更できません！",
                "組み込みの「Self（ユーザー設定）」キャラクターは削除できません！",
            ),
        ],
    )
    def test_self_persona_protection_errors_preserve_identifier(
        self,
        tmp_path: Path,
        lang: str,
        expected_into_self: str,
        expected_prefix_lock: str,
        expected_delete: str,
    ) -> None:
        assert SELF_PERSONA_NAME == "自设"
        self_char = Character(
            id="__self__",
            name=SELF_PERSONA_NAME,
            color="#ffffff",
            sprite_prefix=SELF_PERSONA_SPRITE_PREFIX,
            is_builtin=True,
            pinned=True,
            undeletable=True,
        )
        mika = Character(name="Mika", color="#ffffff", sprite_prefix="mika")
        target = _DummyCharTarget([self_char, mika])
        with bind_language(lang):
            with pytest.raises(CharacterProfileError) as exc_into_self:
                save_character_patch(
                    target,
                    {"name": SELF_PERSONA_NAME},
                    original_name="Mika",
                )
            assert str(exc_into_self.value) == expected_into_self

            with pytest.raises(CharacterProfileError) as exc_prefix:
                save_character_patch(
                    target,
                    {"name": SELF_PERSONA_NAME, "sprite_prefix": "custom_dir"},
                    original_name=SELF_PERSONA_NAME,
                )
            assert str(exc_prefix.value) == expected_prefix_lock

            renamed, _, _ = save_character_patch(
                target,
                {"name": "Other"},
                original_name=SELF_PERSONA_NAME,
            )
            assert renamed.name == "Other"
            assert renamed.id == "__self__"
            target._items[0] = renamed

            del_msg, _names = delete_character_and_assets(
                target,
                "Other",
                upload_dir=tmp_path,
                voice_dir=tmp_path,
                model_dir=tmp_path,
            )
            assert del_msg == expected_delete
            assert is_operation_error_message(del_msg) is True

    @pytest.mark.parametrize(
        ("lang", "expected"),
        [
            ("zh_CN", "YAML配置缺少必需字段"),
            ("en", "missing required fields"),
            ("ja", "必要なフィールド"),
        ],
    )
    def test_character_config_missing_fields_localized(
        self, tmp_path: Path, lang: str, expected: str
    ) -> None:
        cfg_file = tmp_path / "chars.yaml"
        cfg_file.write_text("- name: OnlyName\n", encoding="utf-8")
        with bind_language(lang):
            with pytest.raises(ValueError, match=expected):
                CharacterConfig.read_from_files(str(cfg_file))


class TestSdkPresenterHandlerAndValidatorsI18n:
    @pytest.mark.parametrize(
        ("lang", "expected_401", "expected_402", "expected_429", "expected_502", "expected_mod"),
        [
            ("zh_CN", "未授权", "额度或余额不足", "请求过于频繁", "服务商暂时异常：HTTP 502", "缺少 Python 模块：opencc"),
            ("en", "unauthorized", "quota or balance is insufficient", "rate limit", "temporarily unavailable: HTTP 502", "Missing Python module required for LLM runtime: opencc"),
            ("ja", "認証に失敗", "クォータまたは残高が不足", "リクエスト頻度が高すぎる", "一時的なエラーが発生しています（HTTP 502）", "Python モジュールが不足しています：opencc"),
        ],
    )
    def test_presenter_messages_trilingual(
        self,
        lang: str,
        expected_401: str,
        expected_402: str,
        expected_429: str,
        expected_502: str,
        expected_mod: str,
    ) -> None:
        with bind_language(lang):
            assert expected_401 in llm_http_action_message(401, "unauthorized", timeout=False)
            assert expected_402 in llm_http_action_message(402, "payment required", timeout=False)
            assert expected_429 in llm_http_action_message(429, "rate limit", timeout=False)
            assert expected_502 in llm_http_action_message(502, "bad gateway", timeout=False)
            mod_msg = format_llm_exception_message(
                ModuleNotFoundError("No module named 'opencc'", name="opencc"),
                fallback_message="fallback",
            )
            assert expected_mod in mod_msg

    @pytest.mark.parametrize(
        ("lang", "expected"),
        [
            ("zh_CN", "Shinsekai 启动失败：RuntimeError: boom"),
            ("en", "Shinsekai failed to start: RuntimeError: boom"),
            ("ja", "Shinsekai の起動に失敗しました：RuntimeError: boom"),
        ],
    )
    def test_handler_dialog_message_trilingual(self, lang: str, expected: str) -> None:
        with bind_language(lang):
            assert _format_dialog_message("Shinsekai", RuntimeError("boom"), None) == expected

    @pytest.mark.parametrize(
        ("lang", "expected_empty", "expected_range", "expected_title"),
        [
            ("zh_CN", "Field: 不能为空", "Speed: 必须介于 1–10，当前为 99", "提示:"),
            ("en", "Field: cannot be empty", "Speed: must be between 1–10, got 99", "Notice:"),
            ("ja", "Field: 空にすることはできません", "Speed: 1–10 の範囲内である必要があります（現在値: 99）", "お知らせ:"),
        ],
    )
    def test_validators_and_default_warning_title_trilingual(
        self,
        lang: str,
        expected_empty: str,
        expected_range: str,
        expected_title: str,
    ) -> None:
        with bind_language(lang):
            ok, msg = validators.not_empty("", "Field")
            assert ok is False
            assert msg == expected_empty

            ok2, msg2 = validators.in_range(99, 1, 10, "Speed")
            assert ok2 is False
            assert msg2 == expected_range

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                assert validators.warn_if_invalid((False, ["bad"])) is False
                assert validators.validate_or_block((False, "bad")) is False
                assert validators.warn_if_invalid((False, ["bad"]), title="Custom") is False
            assert str(caught[0].message).startswith(expected_title)
            assert str(caught[1].message).startswith(expected_title)
            assert str(caught[2].message).startswith("Custom:")


class TestPackagingArchiveErrorsI18n:
    @pytest.mark.parametrize(
        ("lang", "expected_prefix"),
        [
            ("zh_CN", "文件未找到:"),
            ("en", "File not found:"),
            ("ja", "ファイルが見つかりません:"),
        ],
    )
    def test_stage_package_import_missing_archive_trilingual(
        self, tmp_path: Path, lang: str, expected_prefix: str
    ) -> None:
        missing = tmp_path / "does_not_exist.zip"
        with bind_language(lang):
            with pytest.raises(FileNotFoundError, match=expected_prefix):
                stage_background_package_import(
                    missing,
                    existing_configs=[],
                    background_upload_dir=tmp_path / "bg",
                    bgm_upload_dir=tmp_path / "bgm",
                )
            with pytest.raises(FileNotFoundError, match=expected_prefix):
                stage_character_package_import(
                    missing,
                    existing_names=[],
                    existing_prefixes=[],
                    sprite_dir=tmp_path / "sp",
                    speech_dir=tmp_path / "vo",
                    model_dir=tmp_path / "mo",
                )
            with pytest.raises(FileNotFoundError, match=expected_prefix):
                stage_effect_package_import(
                    missing,
                    existing_effects=[],
                    effect_root=tmp_path / "ef",
                )
