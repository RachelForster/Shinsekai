"""Unit tests for i18n — translation loading, fallback, parameter substitution."""

import pytest

from i18n import (
    tr,
    tr_in_bundle,
    init_i18n,
    current_language,
    SUPPORTED_LANGS,
    normalize_lang,
)


class TestInitI18n:
    def test_default_language_is_zh_CN(self):
        assert current_language() == "zh_CN"

    def test_init_english(self):
        init_i18n("en")
        assert current_language() == "en"

    def test_init_japanese(self):
        init_i18n("ja")
        assert current_language() == "ja"

    def test_init_normalizes_code(self):
        init_i18n("EN")
        assert current_language() == "en"

    def test_init_unknown_falls_back_to_zh_CN(self):
        init_i18n("fr")
        assert current_language() == "zh_CN"

    def test_init_none_falls_back(self):
        init_i18n(None)
        assert current_language() == "zh_CN"


class TestTr:
    def test_returns_translated_string(self):
        init_i18n("en")
        s = tr("main.window_title")
        assert isinstance(s, str)
        assert len(s) > 0

    def test_missing_key_falls_back_to_en(self):
        init_i18n("ja")
        # Key that exists in en but we use ja bundle
        s = tr("main.window_title")
        assert isinstance(s, str)
        assert len(s) > 0

    def test_nonexistent_key_returns_key_itself(self):
        init_i18n("zh_CN")
        s = tr("this.key.does.not.exist.xyz")
        assert s == "this.key.does.not.exist.xyz"

    def test_parameter_substitution(self):
        init_i18n("en")
        s = tr("main.notify_tool_calling", name="TestTool")
        assert "TestTool" in s

    def test_parameter_substitution_with_missing_key(self):
        """Missing format keys are silently ignored."""
        init_i18n("en")
        s = tr("main.window_title", missing_key="ignored")
        assert isinstance(s, str)
        assert len(s) > 0


class TestTrInBundle:
    def test_returns_from_specified_bundle(self):
        s = tr_in_bundle("main.window_title", "en")
        assert isinstance(s, str)
        assert len(s) > 0

    def test_does_not_change_current_language(self):
        init_i18n("zh_CN")
        s = tr_in_bundle("main.window_title", "ja")
        assert current_language() == "zh_CN"
        assert isinstance(s, str)

    def test_missing_key_falls_back(self):
        s = tr_in_bundle("this.key.does.not.exist.xyz", "en")
        assert s == "this.key.does.not.exist.xyz"

    def test_parameter_in_bundle(self):
        s = tr_in_bundle("main.notify_tool_calling", "en", name="MyTool")
        assert "MyTool" in s


class TestSupportedLangs:
    def test_three_languages(self):
        assert len(SUPPORTED_LANGS) == 3
        assert "zh_CN" in SUPPORTED_LANGS
        assert "en" in SUPPORTED_LANGS
        assert "ja" in SUPPORTED_LANGS


class TestNormalizeLang:
    def test_supported_codes(self):
        assert normalize_lang("zh_CN") == "zh_CN"
        assert normalize_lang("en") == "en"
        assert normalize_lang("ja") == "ja"

    def test_case_variants(self):
        assert normalize_lang("EN") == "en"
        assert normalize_lang("JA") == "ja"

    def test_hyphen_underscore(self):
        assert normalize_lang("zh-CN") == "zh_CN"

    def test_zh_variants(self):
        assert normalize_lang("zh") == "zh_CN"
        assert normalize_lang("Chinese") == "zh_CN"

    def test_ja_variants(self):
        assert normalize_lang("japanese") == "ja"

    def test_en_variants(self):
        assert normalize_lang("english") == "en"

    def test_none(self):
        assert normalize_lang(None) == "zh_CN"

    def test_empty(self):
        assert normalize_lang("") == "zh_CN"

    def test_unknown(self):
        assert normalize_lang("fr") == "zh_CN"


class TestAllLocaleKeysExist:
    """Verify every key in zh_CN has a corresponding entry in en and ja."""
    import json
    from pathlib import Path

    _LOCALES = Path(__file__).resolve().parent.parent.parent / "i18n" / "locales"

    @pytest.fixture(autouse=True)
    def _init_bundles(self):
        init_i18n("zh_CN")

    def _walk_keys(self, d, prefix=""):
        for k, v in d.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                yield from self._walk_keys(v, path)
            else:
                yield path

    def _load(self, code):
        p = self._LOCALES / f"{code}.json"
        if p.is_file():
            with open(p, encoding="utf-8") as f:
                return self.json.load(f)
        return {}

    def test_zh_keys_exist_in_en(self):
        zh = self._load("zh_CN")
        en = self._load("en")
        for key in self._walk_keys(zh):
            path = key.split(".")
            cur = en
            for part in path:
                cur = cur.get(part, None)
                if cur is None:
                    break
            assert cur is not None, f"Key '{key}' missing in en.json"

    def test_zh_keys_exist_in_ja(self):
        zh = self._load("zh_CN")
        ja = self._load("ja")
        for key in self._walk_keys(zh):
            path = key.split(".")
            cur = ja
            for part in path:
                cur = cur.get(part, None)
                if cur is None:
                    break
            assert cur is not None, f"Key '{key}' missing in ja.json"
