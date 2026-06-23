import hashlib
import json

from ui.settings_ui.tts.tts_bundle_manifest import (
    bundle_manifest_for_key,
    load_tts_bundle_manifest,
)


def test_builtin_manifest_contains_download_metadata():
    entry = bundle_manifest_for_key("gpt_sovits_v2pro")

    assert entry is not None
    assert entry.filename == "GPT-SoVITS-v2pro-20250604.7z"
    assert entry.size == 8_185_086_602
    assert (
        entry.sha256
        == "bd60d0796553ff05d8568136e199c13e0dc22ebe2ed24273134e34ed6f215cd6"
    )


def test_manifest_loader_reads_json_file(tmp_path):
    payload = b"bundle-content"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "bundles": [
                    {
                        "kind": "demo",
                        "bundle_dir_key": "demo_bundle",
                        "filename": "demo.7z",
                        "download_url": "https://example.test/demo.7z",
                        "size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest = load_tts_bundle_manifest(manifest_path)

    assert manifest["demo"].bundle_dir_key == "demo_bundle"
    assert manifest["demo"].size == len(payload)
