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
                self.assertIn("classic-dark", theme_index)
                self.assertIn("light-paper", theme_index)
                self.assertEqual(theme_index["classic-dark"]["source"], "builtin")
                self.assertEqual(theme_index["light-paper"]["source"], "builtin")
                self.assertTrue((Path(tempdir) / "data" / "chat_ui_themes" / "classic-dark" / "theme.json").is_file())
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
                self.assertIn("classic-dark", theme_index)
                manifest = get_chat_theme_manifest(state, "classic-dark")
                self.assertEqual(manifest["tokens"]["logs"]["code"]["background"], "rgba(8,9,14,0.9)")
            finally:
                os.chdir(previous_cwd)

    def test_set_active_theme_persists_existing_theme(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                result = set_active_chat_theme(state, {"id": "classic-dark"})
                self.assertEqual(result, {"id": "classic-dark"})
                self.assertEqual(state.config_manager.config.system_config.chat_ui_theme_id, "classic-dark")
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
                    delete_chat_theme(state, "classic-dark")
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
                          "padding": 100,
                          "widthPct": 120
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
                self.assertEqual(manifest["tokens"]["dialog"]["padding"], 72)
                self.assertEqual(manifest["tokens"]["dialog"]["widthPct"], 100)
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
