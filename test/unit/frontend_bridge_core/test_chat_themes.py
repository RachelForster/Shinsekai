import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from frontend_bridge_core.chat_themes import (
    delete_chat_theme,
    get_chat_theme_manifest,
    list_chat_themes,
    set_active_chat_theme,
)


class ChatThemeBridgeTests(unittest.TestCase):
    def _make_state(self):
        self.saved = 0

        def save_system_config():
            self.saved += 1

        system_config = SimpleNamespace(chat_ui_theme_id="")
        config_manager = SimpleNamespace(
            config=SimpleNamespace(system_config=system_config),
            save_system_config=save_system_config,
        )
        return SimpleNamespace(config_manager=config_manager)

    def test_list_chat_themes_seeds_builtin_and_marks_source(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                themes = list_chat_themes(state)
                theme_index = {item["id"]: item for item in themes}
                self.assertEqual(list(theme_index), ["neon-night-city", "windborne-adventure"])
                self.assertEqual(theme_index["neon-night-city"]["source"], "builtin")
                self.assertEqual(theme_index["windborne-adventure"]["source"], "builtin")
                self.assertTrue(
                    (Path(tempdir) / "data" / "chat_ui_themes" / "neon-night-city" / "theme.json").is_file()
                )
                self.assertTrue(
                    (Path(tempdir) / "data" / "chat_ui_themes" / "windborne-adventure" / "theme.json").is_file()
                )
            finally:
                os.chdir(previous_cwd)

    def test_list_chat_themes_falls_back_to_tracked_builtin_manifests(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                with patch("frontend_bridge_core.chat_themes._builtin_themes_root", return_value=Path(tempdir) / "missing"):
                    themes = list_chat_themes(state)
                theme_index = {item["id"]: item for item in themes}
                self.assertIn("neon-night-city", theme_index)
                self.assertIn("windborne-adventure", theme_index)
                neon_manifest = get_chat_theme_manifest(state, "neon-night-city")
                self.assertEqual(neon_manifest["tokens"]["global"]["themeColor"], "#00f5ff")
                manifest = get_chat_theme_manifest(state, "windborne-adventure")
                self.assertEqual(manifest["tokens"]["global"]["themeColor"], "#f3cf57")
            finally:
                os.chdir(previous_cwd)

    def test_set_active_theme_persists_existing_theme(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                result = set_active_chat_theme(state, {"id": "windborne-adventure"})
                self.assertEqual(result, {"id": "windborne-adventure"})
                self.assertEqual(state.config_manager.config.system_config.chat_ui_theme_id, "windborne-adventure")
                self.assertEqual(self.saved, 1)
            finally:
                os.chdir(previous_cwd)

    def test_delete_builtin_theme_is_rejected(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                list_chat_themes(state)
                with self.assertRaises(PermissionError):
                    delete_chat_theme(state, "windborne-adventure")
                with self.assertRaises(PermissionError):
                    delete_chat_theme(state, "neon-night-city")
            finally:
                os.chdir(previous_cwd)

    def test_list_chat_themes_skips_invalid_theme_directories(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                invalid_theme_dir = Path(tempdir) / "data" / "chat_ui_themes" / "broken-theme"
                invalid_theme_dir.mkdir(parents=True, exist_ok=True)
                (invalid_theme_dir / "theme.json").write_text(
                    '{"schema":1,"id":"broken-theme","name":{"en":"Broken"},"tokens":{"dialog":{"background":"red; position:absolute"}}}',
                    encoding="utf-8",
                )

                themes = list_chat_themes(state)
                self.assertNotIn("broken-theme", {item["id"] for item in themes})
            finally:
                os.chdir(previous_cwd)

    def test_get_chat_theme_manifest_returns_normalized_manifest(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                theme_dir = Path(tempdir) / "data" / "chat_ui_themes" / "custom-theme"
                theme_dir.mkdir(parents=True, exist_ok=True)
                (theme_dir / "theme.json").write_text(
                    """
                    {
                      "schema": 1,
                      "id": "wrong-id",
                      "name": { "en": "Custom Theme" },
                      "tokens": {
                        "dialog": {
                          "background": "rgba(10,10,10,0.9)",
                          "chrome": "none",
                          "frameImage": "assets/dialog-frame.svg",
                          "frameSlice": 500,
                          "heightPx": 999,
                          "padding": 100,
                          "textAlign": "center",
                          "textShadow": "0 2px 4px rgba(0,0,0,0.7)",
                          "textSizePx": 80,
                          "textWeight": 950,
                          "widthPct": 120
                        },
                        "name": {
                          "align": "center",
                          "decoration": "line-dots",
                          "fontFamily": "Trebuchet MS, Georgia, serif",
                          "hideWhenStartOption": true,
                          "textSizePx": 4,
                          "textWeight": 100
                        },
                        "options": {
                          "icon": "chat",
                          "maxWidthVw": 90,
                          "minHeightPx": 200,
                          "minWidthVw": 4,
                          "placement": "right",
                          "textSizeVh": 12,
                          "textSizePx": 80,
                          "textWeight": 950,
                          "widthPx": 900,
                          "widthMode": "content"
                        },
                        "input": {
                          "layout": "pill",
                          "maxWidthPx": 999,
                          "sendPlacement": "inside"
                        },
                        "toolbar": {
                          "placement": "dialog-top",
                          "reveal": "hover"
                        },
                        "logs": {
                          "code": {
                            "background": "rgba(8,9,14,0.9)",
                            "fontFamily": "JetBrains Mono, monospace"
                          },
                          "line": {
                            "hover": { "background": "rgba(80,80,100,0.2)" }
                          },
                          "levels": {
                            "error": { "color": "#ff8890" }
                          }
                        },
                        "typewriter": { "cps": 500 }
                      }
                    }
                    """,
                    encoding="utf-8",
                )

                manifest = get_chat_theme_manifest(state, "custom-theme")
                self.assertEqual(manifest["id"], "custom-theme")
                self.assertEqual(manifest["tokens"]["dialog"]["frameImage"], "assets/dialog-frame.svg")
                self.assertEqual(manifest["tokens"]["dialog"]["chrome"], "none")
                self.assertEqual(manifest["tokens"]["dialog"]["frameSlice"], 200)
                self.assertEqual(manifest["tokens"]["dialog"]["heightPx"], 260)
                self.assertEqual(manifest["tokens"]["dialog"]["padding"], 72)
                self.assertEqual(manifest["tokens"]["dialog"]["textAlign"], "center")
                self.assertEqual(manifest["tokens"]["dialog"]["textShadow"], "0 2px 4px rgba(0,0,0,0.7)")
                self.assertEqual(manifest["tokens"]["dialog"]["textSizePx"], 64)
                self.assertEqual(manifest["tokens"]["dialog"]["textWeight"], 900)
                self.assertEqual(manifest["tokens"]["dialog"]["widthPct"], 100)
                self.assertEqual(manifest["tokens"]["name"]["align"], "center")
                self.assertEqual(manifest["tokens"]["name"]["decoration"], "line-dots")
                self.assertEqual(manifest["tokens"]["name"]["fontFamily"], "Trebuchet MS, Georgia, serif")
                self.assertEqual(manifest["tokens"]["name"]["hideWhenStartOption"], True)
                self.assertEqual(manifest["tokens"]["name"]["textSizePx"], 12)
                self.assertEqual(manifest["tokens"]["name"]["textWeight"], 300)
                self.assertEqual(manifest["tokens"]["options"]["icon"], "chat")
                self.assertEqual(manifest["tokens"]["options"]["maxWidthVw"], 60)
                self.assertEqual(manifest["tokens"]["options"]["minHeightPx"], 96)
                self.assertEqual(manifest["tokens"]["options"]["minWidthVw"], 12)
                self.assertEqual(manifest["tokens"]["options"]["placement"], "right")
                self.assertEqual(manifest["tokens"]["options"]["textSizeVh"], 4)
                self.assertEqual(manifest["tokens"]["options"]["textSizePx"], 64)
                self.assertEqual(manifest["tokens"]["options"]["textWeight"], 900)
                self.assertEqual(manifest["tokens"]["options"]["widthPx"], 720)
                self.assertEqual(manifest["tokens"]["options"]["widthMode"], "content")
                self.assertEqual(manifest["tokens"]["input"]["layout"], "pill")
                self.assertEqual(manifest["tokens"]["input"]["maxWidthPx"], 900)
                self.assertEqual(manifest["tokens"]["input"]["sendPlacement"], "inside")
                self.assertEqual(manifest["tokens"]["toolbar"]["placement"], "dialog-top")
                self.assertEqual(manifest["tokens"]["toolbar"]["reveal"], "hover")
                self.assertEqual(manifest["tokens"]["logs"]["code"]["background"], "rgba(8,9,14,0.9)")
                self.assertEqual(manifest["tokens"]["logs"]["code"]["fontFamily"], "JetBrains Mono, monospace")
                self.assertEqual(
                    manifest["tokens"]["logs"]["line"]["hover"]["background"],
                    "rgba(80,80,100,0.2)",
                )
                self.assertEqual(manifest["tokens"]["logs"]["levels"]["error"]["color"], "#ff8890")
                self.assertEqual(manifest["tokens"]["typewriter"]["cps"], 200)
            finally:
                os.chdir(previous_cwd)


if __name__ == "__main__":
    unittest.main()
