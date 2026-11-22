"""Synchronize Python YAML prompt catalogs to Standalone browser locale JSON."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path

from sdk.lang import SUPPORTED_LANGS

from .core.catalog import PROMPT_CATALOG, PromptCatalog

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
STANDALONE_LOCALES_PATH = (
    REPO_ROOT
    / "frontend"
    / "src"
    / "shared"
    / "platform"
    / "standalone"
    / "ai"
    / "generatedTemplateLocales.json"
)
STANDALONE_SESSION_KEYS: tuple[str, ...] = (
    "default_empty_scenario",
    "standalone_fallback_system_prompt",
    "standalone_player_address",
    "standalone_outfit_locked",
    "standalone_outfits_state",
    "standalone_stats_state",
    "list_sep_semi",
    "list_sep_comma",
)


def build_standalone_locales_payload(
    catalog: PromptCatalog = PROMPT_CATALOG,
) -> dict[str, dict[str, str]]:
    payload: dict[str, dict[str, str]] = {}
    for locale in SUPPORTED_LANGS:
        bundle: dict[str, str] = {}
        for full_key in catalog.keys(locale, domain="dialog"):
            short_key = full_key.removeprefix("dialog.")
            bundle[short_key] = catalog.translate(
                full_key,
                locale=locale,
                strict=True,
            )
        for session_key in STANDALONE_SESSION_KEYS:
            if session_key in bundle:
                raise ValueError(
                    f"Duplicate standalone prompt key {session_key!r} across dialog and session catalogs"
                )
            bundle[session_key] = catalog.translate(
                f"session.{session_key}",
                locale=locale,
                strict=True,
            )
        payload[locale] = bundle
    return payload


def render_standalone_locales_json(
    catalog: PromptCatalog = PROMPT_CATALOG,
) -> str:
    payload = build_standalone_locales_payload(catalog)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def sync_standalone_locales(
    *,
    check: bool = False,
    output_path: Path | None = None,
    catalog: PromptCatalog = PROMPT_CATALOG,
) -> bool:
    target = output_path or STANDALONE_LOCALES_PATH
    rendered = render_standalone_locales_json(catalog)
    if check:
        if not target.is_file():
            return False
        current = target.read_text(encoding="utf-8").replace("\r\n", "\n")
        return current == rendered
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(rendered.replace("\r\n", "\n").encode("utf-8"))
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate or verify frontend standalone template locale JSON from YAML catalogs.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if generatedTemplateLocales.json is out of sync with YAML catalogs.",
    )
    args = parser.parse_args(argv)
    ok = sync_standalone_locales(check=args.check)
    if not ok:
        raise SystemExit(
            f"{STANDALONE_LOCALES_PATH} is out of sync with {PROMPT_CATALOG.catalog_dir}; "
            "run: python -m ai.llm.template.sync_standalone"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
