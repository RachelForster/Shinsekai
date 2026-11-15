from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import requests

from application.characters.voice.pipeline.community_models import (
    BILIBILI_SEARCH_URL,
    BILIBILI_SPI_URL,
    HUGGINGFACE_MODELS_API_URL,
    MODELSCOPE_MODELS_API_URL,
    _clean_text,
    _contains_character_token,
    _extract_character_tokens,
    _has_gsv_indicator,
    _safe_nonneg_int,
    _search_bilibili_models,
    _search_huggingface_models,
    _search_modelscope_models,
    search_community_gsv_models,
)


class _MockResponse:
    def __init__(self, payload: Any, *, ok: bool = True, status_code: int = 200) -> None:
        self._payload = payload
        self.ok = ok
        self.status_code = status_code

    def json(self) -> Any:
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


def test_token_extraction_and_word_boundaries_prevent_substring_false_positives():
    tokens = _extract_character_tokens("阿尔托莉雅·潘德拉贡（FGO）", ["Saber", "Artoria", "GPT-SoVITS", "a"])
    assert "阿尔托莉雅·潘德拉贡" in tokens
    assert "阿尔托莉雅" in tokens
    assert "Saber" in tokens
    assert "Artoria" in tokens
    assert "GPT-SoVITS" not in tokens
    assert "a" not in tokens

    assert _contains_character_token("everyone_gpt_sovits", "Ryo") is False
    assert _contains_character_token("stream_gpt_sovits", "Rem") is False
    assert _contains_character_token("ryo_yamada_gpt_sovits", "Ryo") is True
    assert _contains_character_token("RyoYamadaGPTSoVITS", "Ryo Yamada") is True
    assert _contains_character_token("FurinaGPTSoVITS", "Furina") is True


def test_gsv_indicator_distinguishes_gpt_sovits_from_legacy_so_vits_svc():
    assert _has_gsv_indicator("GPT-SoVITS 芙宁娜模型分享") is True
    assert _has_gsv_indicator("模型：GPT—SoVITS @花儿不哭") is True
    assert _has_gsv_indicator("Furina_GSV_v2ProPlus") is True
    assert _has_gsv_indicator("svc-develop-team/so-vits-svc 4.0 翻唱模型") is False
    assert _has_gsv_indicator("RVC 崩铁全角色模型分享") is False


def test_search_community_gsv_models_merges_three_platforms_and_filters_noise(monkeypatch):
    def fake_get(self, url: str, *, params=None, timeout=None, **_kwargs):
        if url == BILIBILI_SPI_URL:
            return _MockResponse({"code": 0, "data": {"b_3": "buvid3_tok", "b_4": "buvid4_tok"}})
        if url == BILIBILI_SEARCH_URL:
            return _MockResponse(
                {
                    "code": 0,
                    "data": {
                        "result": [
                            # Valid model release for Furina
                            {
                                "bvid": "BV13D421E7Ak",
                                "title": '【<em class="keyword">GPT</em>-<em class="keyword">SoVITS</em> <em class="keyword">芙宁娜</em>语音模型分享】',
                                "description": "训练版本 v2ProPlus，夸克网盘自取",
                                "author": "微光",
                                "play": 45000,
                                "favorites": 2400,
                            },
                            # Different character in same game (must be rejected even though query has 原神)
                            {
                                "bvid": "BV1gi421o7Dy",
                                "title": "【原神】钟离 GPT-SoVITS 语音模型分享",
                                "description": "夸克网盘下载",
                                "author": "测试UP",
                                "play": 99999,
                                "favorites": 5000,
                            },
                            # Pure AI cover without model sharing (must be rejected)
                            {
                                "bvid": "BV1xx411c7mD",
                                "title": "【AI芙宁娜】用 GPT-SoVITS 翻唱青花瓷",
                                "description": "仅供试听娱乐",
                                "author": "翻唱UP",
                                "play": 80000,
                                "favorites": 3000,
                            },
                            # Legacy so-vits-svc 4.0 singing model without GPT (must be rejected)
                            {
                                "bvid": "BV1Eu4y1Z7qS",
                                "title": "【AI芙宁娜】冬の花（模型分享）",
                                "description": "sovits项目地址：https://github.com/svc-develop-team/so-vits",
                                "author": "SVC_UP",
                                "play": 70000,
                                "favorites": 2000,
                            },
                            # Invalid bvid (must be rejected)
                            {
                                "bvid": "BV_BAD_ID",
                                "title": "芙宁娜 GPT-SoVITS 模型分享",
                                "description": "下载",
                            },
                        ]
                    },
                }
            )
        if url == HUGGINGFACE_MODELS_API_URL:
            return _MockResponse(
                [
                    # Valid HF repo
                    {
                        "id": "PJMixers-Dev/GPT-SoVITS-Genshin-Impact-Furina",
                        "private": False,
                        "downloads": 120,
                        "likes": 8,
                        "tags": ["text-to-speech", "en", "region:us"],
                    },
                    # Official base repo (must be rejected)
                    {
                        "id": "lj1995/GPT-SoVITS",
                        "private": False,
                        "downloads": 500000,
                        "likes": 9999,
                        "tags": ["Furina"],
                    },
                    # Private repo (must be rejected)
                    {
                        "id": "SecretUser/Furina-GPT-SoVITS",
                        "private": True,
                        "downloads": 10,
                        "likes": 1,
                    },
                    # Unrelated character in Genshin (must be rejected)
                    {
                        "id": "PJMixers-Dev/GPT-SoVITS-Genshin-Impact-Nahida",
                        "private": False,
                        "downloads": 300,
                        "likes": 12,
                    },
                    # Path traversal segment (must be rejected)
                    {
                        "id": "../Furina-GPT-SoVITS",
                        "private": False,
                    },
                ]
            )
        return _MockResponse({}, ok=False, status_code=404)

    def fake_put(self, url: str, *, json=None, timeout=None, **_kwargs):
        assert url == MODELSCOPE_MODELS_API_URL
        assert "GPT-SoVITS" in json["Name"]
        return _MockResponse(
            {
                "Data": {
                    "Model": {
                        "Models": [
                            {
                                "Path": "leletxh",
                                "Name": "Furina_GPT_SoVITS",
                                "ChineseName": "芙宁娜GPT-SoVITS模型",
                                "Description": "使用1.36时长的数据集（剧情+简介）",
                                "Downloads": 15,
                                "Likes": None,
                                "Tags": ["tts"],
                            },
                            {
                                "Path": "lj1995",
                                "Name": "GPT-SoVITS-windows-package",
                                "ChineseName": "GPT-SoVITS整合包",
                                "Description": "通用底模",
                                "Downloads": 99999,
                            },
                        ]
                    }
                }
            }
        )

    monkeypatch.setattr("application.characters.voice.pipeline.community_models.requests.Session.get", fake_get)
    monkeypatch.setattr("application.characters.voice.pipeline.community_models.requests.Session.put", fake_put)

    results = search_community_gsv_models(
        "芙宁娜",
        "芙宁娜 原神 语音合集",
        aliases=["Furina"],
        max_results=5,
    )

    urls = [item["url"] for item in results]
    platforms = {item["platform"] for item in results}
    assert platforms == {"bilibili", "modelscope", "huggingface"}
    assert urls.count("https://www.bilibili.com/video/BV13D421E7Ak") == 1
    assert urls.count("https://modelscope.cn/models/leletxh/Furina_GPT_SoVITS") == 1
    assert urls.count("https://huggingface.co/PJMixers-Dev/GPT-SoVITS-Genshin-Impact-Furina") == 1
    assert len(results) == 3

    bili_hit = next(item for item in results if item["platform"] == "bilibili")
    assert "<em" not in bili_hit["title"]


def test_search_community_gsv_models_returns_empty_for_original_character_or_network_errors(monkeypatch):
    # First: generic GSV results exist, but none match original character "望月澪"
    monkeypatch.setattr(
        "application.characters.voice.pipeline.community_models.requests.Session.get",
        lambda self, url, **_kw: _MockResponse(
            {"code": 0, "data": {"result": [{"bvid": "BV12g4y1m7Uw", "title": "GPT-SoVITS 整合包使用教程分享", "description": "网盘下载"}]}}
            if url == BILIBILI_SEARCH_URL
            else {"code": 0, "data": {}}
        ),
    )
    monkeypatch.setattr(
        "application.characters.voice.pipeline.community_models.requests.Session.put",
        lambda self, url, **_kw: _MockResponse(
            {"Data": {"Model": {"Models": [{"Path": "user1", "Name": "Other_GPT_SoVITS", "ChineseName": "其他角色GPT-SoVITS模型"}]}}}
        ),
    )
    assert search_community_gsv_models("望月澪", "望月澪 语音合集") == []

    # Second: total network outage across all endpoints must never raise
    def raise_timeout(self, *args, **kwargs):
        raise requests.Timeout("simulated timeout")

    monkeypatch.setattr("application.characters.voice.pipeline.community_models.requests.Session.get", raise_timeout)
    monkeypatch.setattr("application.characters.voice.pipeline.community_models.requests.Session.put", raise_timeout)
    assert search_community_gsv_models("芙宁娜", aliases=["Furina"]) == []
    assert search_community_gsv_models("", aliases=["Furina"]) == []
    assert search_community_gsv_models("GPT-SoVITS") == []


def test_defensive_parsers_and_description_or_tag_matches(monkeypatch):
    assert _clean_text("x" * 200, max_len=20) == ("x" * 19) + "…"
    assert _safe_nonneg_int(True) == 0
    assert _safe_nonneg_int("42") == 42
    assert _safe_nonneg_int("bad") == 0
    assert _contains_character_token("", "Ryo") is False
    assert _contains_character_token("abc", "---") is False
    assert _extract_character_tokens("丹・恒", [""]) == ("丹・恒",)

    assert _search_modelscope_models([], ["Ryo"], timeout=1.0) == []
    assert _search_huggingface_models([], ["Ryo"], timeout=1.0) == []
    assert _search_bilibili_models("", ["Ryo"], "", timeout=1.0) == []

    # ModelScope: 1st term HTTP 500, 2nd term succeeds with malformed entries + description-only character hit
    ms_calls = 0

    def fake_ms_put(self, url, *, json=None, timeout=None, **_kw):
        nonlocal ms_calls
        ms_calls += 1
        if ms_calls == 1:
            return _MockResponse({}, ok=False, status_code=500)
        return _MockResponse(
            {
                "Data": {
                    "Model": {
                        "Models": [
                            "not-a-dict",
                            {"Path": "..", "Name": "bad"},
                            {"Path": "u1", "Name": "RVC_Only", "Description": "RVC model for Ryo"},
                            {
                                "Path": "band_user",
                                "Name": "Kessoku_GSV_Pack",
                                "ChineseName": "结束乐队GSV合集",
                                "Description": "包含山田凉与虹夏音色",
                                "Downloads": "18",
                                "Likes": "3",
                                "Tags": ["gsv"],
                            },
                        ]
                    }
                }
            }
        )

    monkeypatch.setattr("application.characters.voice.pipeline.community_models.requests.Session.put", fake_ms_put)
    ms_hits = _search_modelscope_models(["山田凉", "Ryo"], ["山田凉", "Ryo"], timeout=2.0)
    assert len(ms_hits) == 1
    assert ms_hits[0].url == "https://modelscope.cn/models/band_user/Kessoku_GSV_Pack"
    assert ms_hits[0].downloads == 18
    assert ms_hits[0].likes == 3

    # Hugging Face: 1st term non-list JSON, 2nd term has malformed rows + tag-matched GSV model
    hf_calls = 0

    def fake_hf_get(self, url, *, params=None, timeout=None, **_kw):
        nonlocal hf_calls
        hf_calls += 1
        if hf_calls == 1:
            return _MockResponse({"error": "unexpected object"})
        return _MockResponse(
            [
                "not-a-dict",
                {"id": "missing_slash"},
                {"id": "user/rvc_only", "tags": ["Ryo"]},
                {
                    "id": "kessoku/band_gsv_pack",
                    "tags": ["Ryo", "gsv", "text-to-speech"],
                    "downloads": "25",
                    "likes": "4",
                },
            ]
        )

    monkeypatch.setattr("application.characters.voice.pipeline.community_models.requests.Session.get", fake_hf_get)
    hf_hits = _search_huggingface_models(["Ryo", "Yamada"], ["Ryo"], timeout=2.0)
    assert len(hf_hits) == 1
    assert hf_hits[0].url == "https://huggingface.co/kessoku/band_gsv_pack"

    # Bilibili: SPI non-OK, duplicate bvid, description-only match + weak release, and noise + strong release
    def fake_bili_get(self, url, *, params=None, timeout=None, **_kw):
        if url == BILIBILI_SPI_URL:
            return _MockResponse({}, ok=False, status_code=503)
        return _MockResponse(
            {
                "code": 0,
                "data": {
                    "result": [
                        "bad-row",
                        {
                            "bvid": "BV1eqNnzjEWy",
                            "title": "结束乐队 GSV 音色包置顶评论区",
                            "description": "内含山田凉与喜多郁代",
                            "author": "UP1",
                            "play": 500,
                            "favorites": 20,
                        },
                        {
                            "bvid": "BV1eqNnzjEWy",
                            "title": "重复BVID应跳过",
                            "description": "山田凉 GPT-SoVITS 模型分享",
                        },
                        {
                            "bvid": "BV1ab411c7DE",
                            "title": "【AI山田凉】GPT-SoVITS 翻唱附模型分享",
                            "description": "夸克网盘下载",
                            "author": "UP2",
                            "play": 1200,
                            "favorites": 50,
                        },
                    ]
                },
            }
        )

    monkeypatch.setattr("application.characters.voice.pipeline.community_models.requests.Session.get", fake_bili_get)
    bili_hits = _search_bilibili_models("山田凉", ["山田凉"], "孤独摇滚", timeout=2.0)
    assert [h.url for h in bili_hits] == [
        "https://www.bilibili.com/video/BV1eqNnzjEWy",
        "https://www.bilibili.com/video/BV1ab411c7DE",
    ]

