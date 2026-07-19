"""
Shared test fixtures: mock adapters, mock AppRuntime, test data factories.

All test files automatically import fixtures defined here — no manual import needed.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# MUST be first: reconfigure stdout/stderr to UTF-8 BEFORE any project code
# runs and prints non-ASCII text.  Otherwise pytest's capture tempfile will
# contain mixed-encoding bytes and fail during cleanup.
# ---------------------------------------------------------------------------
import sys
import os
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass  # Python < 3.7 or non-reconfigurable streams (e.g. IDLE)

# Make project root importable (tests run from repo root)
_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parent.parent


def _configure_test_temp_dir() -> None:
    temp_root_override = os.environ.get("SHINSEKAI_PYTEST_TEMP_ROOT")
    temp_root = (
        Path(temp_root_override)
        if temp_root_override
        else Path(tempfile.gettempdir()) / "shinsekai-pytest-runtime"
    )
    temp_root.mkdir(parents=True, exist_ok=True)
    temp_path = str(temp_root)
    os.environ.setdefault("TMPDIR", temp_path)
    os.environ.setdefault("TEMP", temp_path)
    os.environ.setdefault("TMP", temp_path)
    os.environ.setdefault("SHINSEKAI_CHAT_ATTACHMENTS_ROOT", temp_path)
    tempfile.tempdir = temp_path


_configure_test_temp_dir()
os.environ.setdefault("SHINSEKAI_SUPPRESS_MAIN_ERROR_DIALOG", "1")

from queue import Queue
from unittest.mock import MagicMock

import pytest

if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sdk.messages import UserInputMessage, LLMDialogMessage, TTSOutputMessage

# Re-export mock adapters from the importable module so fixtures work
from test.mocks import MockLLMAdapter, MockTTSAdapter, MockT2IAdapter, MockASRAdapter


# =========================================================================
# Test Data Factories — create valid Pydantic model instances with defaults
# =========================================================================

from config.schema import (
    Sprite,
    Character,
    Background,
    ApiConfig,
    SystemConfig,
    AppConfig,
)


def make_sprite(path: str = "", voice_path: str = "", voice_text: str = "") -> Sprite:
    """Create a Sprite with an actual temp file if no path given."""
    if not path:
        import tempfile
        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        path = f.name
        f.close()
    return Sprite(path=path, voice_path=voice_path or None, voice_text=voice_text or None)


def make_character(
    name: str = "TestChar",
    color: str = "#ffffff",
    sprite_prefix: str = "test",
    character_setting: str = "You are a test character.",
    **overrides,
) -> Character:
    kw = {
        "name": name,
        "color": color,
        "sprite_prefix": sprite_prefix,
        "character_setting": character_setting,
    }
    kw.update(overrides)
    return Character(**kw)


def make_background(name: str = "TestBg", sprite_prefix: str = "test_bg", **overrides) -> Background:
    kw = {"name": name, "sprite_prefix": sprite_prefix}
    kw.update(overrides)
    return Background(**kw)


def make_api_config(
    llm_provider: str = "Deepseek",
    llm_api_key: dict = None,
    llm_model: dict = None,
    **overrides,
) -> ApiConfig:
    kw = {
        "llm_provider": llm_provider,
        "llm_api_key": llm_api_key or {"Deepseek": "sk-test"},
        "llm_model": llm_model or {"Deepseek": "deepseek-chat"},
        "is_streaming": True,
        "temperature": 0.7,
    }
    kw.update(overrides)
    return ApiConfig(**kw)


def make_system_config(**overrides) -> SystemConfig:
    kw = {
        "ui_language": "zh_CN",
        "voice_language": "ja",
        "base_font_size_px": 56,
    }
    kw.update(overrides)
    return SystemConfig(**kw)


def make_app_config(
    characters: list = None,
    api_config: ApiConfig = None,
    system_config: SystemConfig = None,
    background_list: list = None,
) -> AppConfig:
    return AppConfig(
        characters=characters or [make_character()],
        background_list=background_list or [make_background()],
        api_config=api_config or make_api_config(),
        system_config=system_config or make_system_config(),
    )


def make_user_input(text: str = "Hello") -> UserInputMessage:
    return UserInputMessage(text=text)


def make_llm_dialog(
    name: str = "TestChar",
    text: str = "Hello from LLM",
    asset_id: str = "-1",
    translate: str = "",
    effect: str = "",
) -> LLMDialogMessage:
    return LLMDialogMessage(
        name=name, text=text, asset_id=asset_id, translate=translate, effect=effect
    )


def make_tts_output(
    audio_path: str = "/tmp/fake.wav",
    name: str = "TestChar",
    text: str = "Spoken text",
    asset_id: str = "-1",
    is_system_message: bool = False,
    is_final_segment: bool = True,
) -> TTSOutputMessage:
    return TTSOutputMessage(
        audio_path=audio_path,
        name=name,
        text=text,
        asset_id=asset_id,
        is_system_message=is_system_message,
        is_final_segment=is_final_segment,
    )


# =========================================================================
# Fixtures — shared across all test files
# =========================================================================


@pytest.fixture
def mock_llm_adapter():
    """A MockLLMAdapter with a default canned response."""
    return MockLLMAdapter(responses=["Mock reply."])


@pytest.fixture
def mock_tts_adapter():
    return MockTTSAdapter()


@pytest.fixture
def mock_t2i_adapter():
    return MockT2IAdapter()


@pytest.fixture
def mock_asr_adapter():
    return MockASRAdapter(language="zh")


@pytest.fixture
def sample_app_config():
    """A fully valid AppConfig built from factory functions."""
    return make_app_config()


@pytest.fixture
def sample_llm_dialog():
    return make_llm_dialog()


@pytest.fixture
def sample_tts_output():
    return make_tts_output()


@pytest.fixture
def sample_user_input():
    return make_user_input()


# =========================================================================
# AppRuntime fixture — for tests that need the global singleton
# =========================================================================

from core.runtime.app_runtime import AppRuntime, set_app_runtime


@pytest.fixture
def mock_app_runtime(mock_llm_adapter, sample_app_config):
    """Set up a minimal AppRuntime as the global singleton; cleaned up after test.

    All queues are real queue.Queue instances so worker-like tests can push/pop.
    """
    from config.config_manager import ConfigManager

    # Build a ConfigManager that returns our sample config
    config_mgr = MagicMock(spec=ConfigManager)
    config_mgr.config = sample_app_config
    config_mgr.get_character_by_name.return_value = (
        sample_app_config.characters[0] if sample_app_config.characters else None
    )

    # Minimal LLMManager using the mock adapter
    from llm.llm_manager import LLMManager

    llm_mgr = LLMManager(adapter=mock_llm_adapter, max_tokens=128000)

    ui_update_manager = MagicMock()

    rt = AppRuntime(
        config=config_mgr,
        ui_update_manager=ui_update_manager,
        llm_manager=llm_mgr,
        tts_manager=None,
        t2i_manager=None,
        bgm_list=[],
        user_input_queue=Queue(),
        tts_queue=Queue(),
        audio_path_queue=Queue(),
        text_processor=MagicMock(),
        opencc=MagicMock(),
    )
    # opencc.convert returns input unchanged by default
    rt.opencc.convert.side_effect = lambda s: s

    set_app_runtime(rt)
    yield rt
    set_app_runtime(None)


# =========================================================================
# Custom options
# =========================================================================

def pytest_addoption(parser):
    parser.addoption(
        "--run-ui",
        action="store_true",
        default=False,
        help="Run tests that require a real UI (ChatUIWindow + Qt signalling)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "ui: mark test as requiring a real Qt UI (deselect with '-m \"not ui\"')",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-ui"):
        return  # allow all
    skip_ui = pytest.mark.skip(reason="need --run-ui flag to run UI tests")
    for item in items:
        if "ui" in item.keywords:
            item.add_marker(skip_ui)
