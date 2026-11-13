"""Streaming OpenAI-compatible VLM client for local `Qwen3-VL-2B` perception decisions."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
import json
import logging
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from ai.perception.parser import (
    InvalidPerceptionDecision,
    parse_perception_decision_json,
    try_extract_early_reflex,
)
from ai.perception.prompts import build_perception_messages
from ai.perception.text_tasks import VoiceStyleStore, summarize_episode_batch
from core.perception.models import (
    PerceptionConfig,
    PerceptionDigestResult,
    PerceptionFrame,
    RawPerceptionSnapshot,
    ReflexDecision,
)

logger = logging.getLogger(__name__)

# A 64×64 PNG with three color blocks. The test never reads the shared screen.
_TEST_IMAGE_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAbUlEQVR42u3RQQ2AMBBFwRYN"
    "FVMJ+KACmlRgj1hAAg64VsUSSOYJ+JvJ5tquFNk8euj+ln4eAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAwPvl59xDD4y7+AAAAAAAAAAAAAAAAAAAAAAAAAAAAADAt1pRtwb6I0JewgAAAABJRU5ErkJggg=="
)


class PerceptionInferenceError(RuntimeError):
    """The model server reported an error while processing a decision."""


def _check_inference_error(payload: dict[str, Any]) -> None:
    error = payload.get("error")
    if error:
        detail = error.get("message") if isinstance(error, dict) else error
        raise PerceptionInferenceError(str(detail or "Visual inference failed")[:300])


def _response_ocr_text(payload: dict[str, Any]) -> str:
    metadata = payload.get("shinsekai_perception")
    text = metadata.get("ocrText") if isinstance(metadata, dict) else None
    return text.strip()[:320] if isinstance(text, str) else ""


def _chat_completions_url(base_url: str) -> str:
    clean = str(base_url or "http://127.0.0.1:8091/v1").strip().rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    if clean.endswith("/v1"):
        return f"{clean}/chat/completions"
    return f"{clean}/v1/chat/completions"


def _models_url(base_url: str) -> str:
    clean = str(base_url or "http://127.0.0.1:8091/v1").strip().rstrip("/")
    if clean.endswith("/chat/completions"):
        clean = clean[: -len("/chat/completions")]
    if clean.endswith("/v1"):
        return f"{clean}/models"
    return f"{clean}/v1/models"


class PerceptionDecisionClient:
    """HTTP/SSE transport client for local `Qwen3-VL-2B` inference and lightweight text tasks."""

    def __init__(self, *, voice_style_cache_path: Path | str | None = None) -> None:
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self._voice_styles = VoiceStyleStore(voice_style_cache_path)

    def _open(self, req: urllib.request.Request, timeout: float):
        host = urlsplit(req.full_url).hostname
        if host in {"127.0.0.1", "localhost", "::1"}:
            return self._opener.open(req, timeout=timeout)
        return urllib.request.urlopen(req, timeout=timeout)

    def get_cached_voice_style(self, character_name: str, character_brief: str) -> str | None:
        return self._voice_styles.get_cached(character_name, character_brief)

    def extract_voice_style(
        self,
        character_name: str,
        character_brief: str,
        config: PerceptionConfig,
    ) -> str:
        return self._voice_styles.extract(
            character_name,
            character_brief,
            config,
            complete_text=self.complete_text,
        )

    def summarize_episode(
        self,
        batch: Sequence[tuple[float, str, str]],
        config: PerceptionConfig,
    ) -> str:
        return summarize_episode_batch(batch, config, complete_text=self.complete_text)

    def complete_text(
        self,
        messages: list[dict[str, Any]],
        config: PerceptionConfig,
        max_tokens: int = 96,
        timeout: float | None = None,
    ) -> str:
        """Run a lightweight pure-text completion on the local perception model."""
        url = _chat_completions_url(config.base_url)
        body = {
            "model": config.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": max_tokens,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if config.api_key and config.api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {config.api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        effective_timeout = timeout if timeout is not None else min(6.0, config.request_timeout_sec)
        with self._open(req, timeout=effective_timeout) as resp:
            content, _early, _ocr = self._read_decision_response(resp, None)
        return content.strip()

    def probe_health(self, config: PerceptionConfig, *, timeout: float = 2.5) -> dict[str, Any]:
        """Check whether the configured local perception endpoint is reachable."""
        url = _models_url(config.base_url)
        headers = {"Accept": "application/json"}
        if config.api_key and config.api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {config.api_key}"
        req = urllib.request.Request(url, headers=headers, method="GET")
        t0 = time.perf_counter()
        try:
            with self._open(req, timeout=timeout) as resp:
                raw = resp.read(32768).decode("utf-8", errors="replace")
                latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
                models: list[str] = []
                try:
                    payload = json.loads(raw)
                    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
                        models = [
                            str(item.get("id"))
                            for item in payload["data"]
                            if isinstance(item, dict) and item.get("id")
                        ]
                except json.JSONDecodeError:
                    pass
                configured_model = str(config.model or "").strip()
                model_present = True if not models or not configured_model else (configured_model in models)
                return {
                    "ok": True,
                    "url": url,
                    "baseUrl": config.base_url,
                    "configuredModel": configured_model,
                    "modelPresent": model_present,
                    "latencyMs": latency_ms,
                    "models": models,
                }
        except Exception as exc:
            return {
                "ok": False,
                "url": url,
                "baseUrl": config.base_url,
                "configuredModel": str(config.model or "").strip(),
                "error": str(exc),
                "models": [],
            }

    def read_screen_text(self, frame: PerceptionFrame, config: PerceptionConfig) -> str:
        if not config.use_local_ocr:
            return ""
        url = _models_url(config.base_url).removesuffix("/models") + "/perception/ocr"
        body: dict[str, Any] = {"image": frame.to_data_url()}
        if frame.ocr_scope is not None:
            body["ocrScope"] = frame.ocr_scope.to_payload()
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._open(req, timeout=min(4.0, config.request_timeout_sec)) as response:
            payload = json.load(response)
        _check_inference_error(payload)
        return _response_ocr_text(payload)

    def decide(
        self,
        snapshot: RawPerceptionSnapshot,
        config: PerceptionConfig,
        *,
        previous_digest: str = "",
        character_name: str = "",
        character_brief: str = "",
        voice_style: str = "",
        scene_anchor: str = "",
        recent_subtitles: Sequence[str] = (),
        recent_barks: Sequence[str] = (),
        sprite_choices: Mapping[int, str] | None = None,
        reaction_guidance: str = "",
        previous_frame: PerceptionFrame | None = None,
        screen_text: str | None = None,
        previous_screen_text: str = "",
        screen_text_changed: bool | None = None,
        retry_unreadable: bool = True,
        on_early_reflex: Callable[[ReflexDecision], None] | None = None,
    ) -> PerceptionDigestResult:
        """Run streaming inference on `snapshot`, firing `on_early_reflex` mid-stream."""
        compared_frames = False
        repeated_frame = False
        limited_ocr = (
            config.use_local_ocr and snapshot.frame is not None and snapshot.frame.ocr_scope is not None
            and snapshot.frame.ocr_scope.mode != "full"
        )
        if screen_text is not None and snapshot.frame is not None and snapshot.frame.source == "screen_share":
            from ai.perception.frames import prepare_screen_frame

            repeated_frame = (
                previous_frame is not None
                and snapshot.frame.image_base64 == previous_frame.image_base64
                and not screen_text_changed
                and not (snapshot.states or snapshot.events)
            )
            frame, compared_frames = prepare_screen_frame(
                snapshot.frame, None if repeated_frame else previous_frame, config.frame_max_side,
            )
            snapshot = replace(snapshot, frame=frame)
        if repeated_frame:
            previous_digest = ""
            scene_anchor = ""
            on_early_reflex = None
        messages = build_perception_messages(
            snapshot,
            previous_digest=previous_digest,
            character_name=character_name,
            character_brief=character_brief,
            voice_style=voice_style,
            scene_anchor=scene_anchor,
            recent_subtitles=recent_subtitles,
            recent_barks=recent_barks,
            sprite_choices=sprite_choices,
            reaction_guidance=reaction_guidance,
            reflex_enabled=config.reflex_enabled and not repeated_frame,
            compared_frames=compared_frames,
            screen_text=screen_text or "",
            previous_screen_text=previous_screen_text,
            screen_text_changed=screen_text_changed,
            limited_ocr=limited_ocr,
        )
        url = _chat_completions_url(config.base_url)
        body = {
            "model": config.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 192,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json",
        }
        if urlsplit(url).hostname in {"127.0.0.1", "localhost", "::1"}:
            headers["X-Shinsekai-Perception-Decision"] = "1"
        use_ocr = (
            screen_text is None and config.use_local_ocr
            and snapshot.frame is not None and snapshot.frame.source == "screen_share"
            and snapshot.frame.ocr_scope is None
        )
        if use_ocr:
            headers["X-Shinsekai-OCR-Frame-Max-Side"] = str(config.frame_max_side)
        if config.api_key and config.api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {config.api_key}"

        t0 = time.perf_counter()

        def attempt(*, stream: bool) -> tuple[PerceptionDigestResult, bool]:
            req = urllib.request.Request(
                url,
                data=json.dumps({**body, "stream": stream}, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                with self._open(req, timeout=config.request_timeout_sec) as resp:
                    content, early_fired, ocr_text = self._read_decision_response(resp, on_early_reflex)
            except urllib.error.HTTPError as exc:
                try:
                    error_payload = json.loads(exc.read(8192))
                except (ValueError, OSError):
                    raise exc
                if isinstance(error_payload, dict):
                    _check_inference_error(error_payload)
                raise
            latency = (time.perf_counter() - t0) * 1000.0
            try:
                result = parse_perception_decision_json(content, game=snapshot.primary_game, latency_ms=latency)
            except InvalidPerceptionDecision:
                if not (use_ocr and ocr_text and not retry_unreadable):
                    raise
                result = PerceptionDigestResult(game=snapshot.primary_game, latency_ms=latency)
            if repeated_frame and result.reflex.act:
                result = replace(result, reflex=ReflexDecision())
            if limited_ocr and result.screen_text:
                result = replace(result, screen_text="")
            return replace(result, ocr_text=ocr_text if use_ocr else ""), early_fired

        try:
            result, early_fired = attempt(stream=True)
        except InvalidPerceptionDecision:
            if not retry_unreadable:
                raise
            logger.debug("Retrying unreadable streaming perception response without streaming")
            result, early_fired = attempt(stream=False)

        if not early_fired and on_early_reflex is not None and result.reflex.act:
            try:
                on_early_reflex(result.reflex)
            except Exception:
                logger.exception("post-stream reflex callback failed")
        return result

    def probe_image(self, config: PerceptionConfig) -> dict[str, Any]:
        health = self.probe_health(config)
        if not health["ok"] or health.get("modelPresent") is False:
            return health
        snapshot = RawPerceptionSnapshot(
            states={},
            events=(),
            frame=PerceptionFrame(_TEST_IMAGE_BASE64, mime_type="image/png", width=64, height=64),
            revision=0,
        )
        try:
            result = self.decide(snapshot, config)
            if not result.digest:
                raise InvalidPerceptionDecision("Visual model did not describe the test image")
            health["imageTest"] = {"ok": True}
        except Exception as exc:
            health["imageTest"] = {"ok": False, "error": str(exc)[:300]}
        return health

    @staticmethod
    def _read_decision_response(
        response: Any,
        on_early_reflex: Callable[[ReflexDecision], None] | None,
    ) -> tuple[str, bool, str]:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "text/event-stream" not in content_type:
            try:
                payload = json.loads(response.read())
            except ValueError as exc:
                raise InvalidPerceptionDecision("Visual server returned an unreadable response") from exc
            if not isinstance(payload, dict):
                return "", False, ""
            _check_inference_error(payload)
            choices = payload.get("choices") or []
            if choices and isinstance(choices[0], dict):
                message = choices[0].get("message") or {}
                return str(message.get("content") or ""), False, _response_ocr_text(payload)
            return "", False, _response_ocr_text(payload)

        accumulated = ""
        early_fired = False
        ocr_text = ""
        for raw_line in response:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data:"):
                continue
            data_str = line[5:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except ValueError:
                continue
            if not isinstance(chunk, dict):
                continue
            _check_inference_error(chunk)
            ocr_text = _response_ocr_text(chunk) or ocr_text
            choices = chunk.get("choices") or []
            if not choices or not isinstance(choices[0], dict):
                continue
            delta = choices[0].get("delta") or {}
            piece = delta.get("content")
            if not piece:
                continue
            accumulated += str(piece)
            if not early_fired and on_early_reflex is not None:
                early = try_extract_early_reflex(accumulated)
                if early is not None and early.act:
                    early_fired = True
                    try:
                        on_early_reflex(early)
                    except Exception:
                        logger.exception("early reflex callback failed")
        return accumulated, early_fired, ocr_text
