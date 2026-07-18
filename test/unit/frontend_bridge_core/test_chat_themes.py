import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from frontend_bridge_core.chat_themes import (
    BUILTIN_THEME_OWNER_MARKER,
    _is_builtin_theme_dir,
    delete_chat_theme,
    get_chat_theme_manifest,
    list_chat_themes,
    save_chat_theme,
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
                self.assertEqual(list(theme_index), ["neon-night-city", "sakura-dream", "windborne-adventure"])
                self.assertEqual(theme_index["neon-night-city"]["source"], "builtin")
                self.assertEqual(theme_index["sakura-dream"]["source"], "builtin")
                self.assertEqual(theme_index["windborne-adventure"]["source"], "builtin")
                self.assertTrue(
                    (Path(tempdir) / "data" / "chat_ui_themes" / "neon-night-city" / "theme.json").is_file()
                )
                self.assertTrue(
                    (
                        Path(tempdir)
                        / "data"
                        / "chat_ui_themes"
                        / "neon-night-city"
                        / "frame-dialog.svg"
                    ).is_file()
                )
                self.assertTrue(
                    (Path(tempdir) / "data" / "chat_ui_themes" / "windborne-adventure" / "theme.json").is_file()
                )
                self.assertTrue(
                    (Path(tempdir) / "data" / "chat_ui_themes" / "sakura-dream" / "preview.png").is_file()
                )
                self.assertTrue(
                    (
                        Path(tempdir)
                        / "data"
                        / "chat_ui_themes"
                        / "sakura-dream"
                        / BUILTIN_THEME_OWNER_MARKER
                    ).is_file()
                )
            finally:
                os.chdir(previous_cwd)

    def test_missing_builtin_assets_do_not_create_python_manifest_fallbacks(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                with patch("frontend_bridge_core.chat_themes._builtin_themes_root", return_value=Path(tempdir) / "missing"):
                    themes = list_chat_themes(state)
                    self.assertEqual(themes, [])
                    with self.assertRaises(FileNotFoundError):
                        get_chat_theme_manifest(state, "windborne-adventure")
                default_theme_dir = Path(tempdir) / "data" / "chat_ui_themes" / "windborne-adventure"
                self.assertFalse(default_theme_dir.exists())
            finally:
                os.chdir(previous_cwd)

    def test_list_chat_themes_refreshes_outdated_builtin_assets(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                target = Path(tempdir) / "data" / "chat_ui_themes" / "neon-night-city"
                target.mkdir(parents=True)
                (target / "theme.json").write_text(
                    '{"schema":1,"id":"neon-night-city","name":{"en":"Old Neon"},"version":"1.0.0","tokens":{}}',
                    encoding="utf-8",
                )

                themes = list_chat_themes(state)

                theme_index = {item["id"]: item for item in themes}
                self.assertEqual(theme_index["neon-night-city"]["version"], "1.3.2")
                self.assertTrue((target / "frame-dialog.svg").is_file())
                self.assertTrue((target / BUILTIN_THEME_OWNER_MARKER).is_file())
            finally:
                os.chdir(previous_cwd)

    def test_preexisting_sakura_dream_stays_user_owned_and_is_not_refreshed(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                target = Path(tempdir) / "data" / "chat_ui_themes" / "sakura-dream"
                target.mkdir(parents=True)
                original_manifest = (
                    '{"schema":1,"id":"sakura-dream","name":{"en":"My Sakura"},"tokens":{}}'
                )
                (target / "theme.json").write_text(original_manifest, encoding="utf-8")
                (target / "frame-dialog.svg").write_text("user-owned-frame", encoding="utf-8")

                themes = list_chat_themes(state)

                summary = next(theme for theme in themes if theme["id"] == "sakura-dream")
                self.assertEqual(summary["source"], "user")
                self.assertEqual((target / "theme.json").read_text(encoding="utf-8"), original_manifest)
                self.assertEqual((target / "frame-dialog.svg").read_text(encoding="utf-8"), "user-owned-frame")
                self.assertFalse((target / BUILTIN_THEME_OWNER_MARKER).exists())

                delete_chat_theme(state, "sakura-dream")
                self.assertFalse(target.exists())
            finally:
                os.chdir(previous_cwd)

    def test_builtin_owner_marker_is_only_trusted_under_the_registered_theme_root(self):
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                spoofed_dir = Path(tempdir) / "outside" / "sakura-dream"
                spoofed_dir.mkdir(parents=True)
                (spoofed_dir / BUILTIN_THEME_OWNER_MARKER).write_text(
                    "sakura-dream\n", encoding="utf-8"
                )

                self.assertFalse(_is_builtin_theme_dir("sakura-dream"))
            finally:
                os.chdir(previous_cwd)

    def test_missing_non_default_builtin_falls_back_to_default_manifest(self):
        state = self._make_state()
        project_root = Path(__file__).resolve().parents[3]
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            builtin_root = Path(tempdir) / "builtin"
            shutil.copytree(
                project_root / "assets" / "chat_ui_themes" / "windborne-adventure",
                builtin_root / "windborne-adventure",
            )
            os.chdir(tempdir)
            try:
                with patch("frontend_bridge_core.chat_themes._builtin_themes_root", return_value=builtin_root):
                    themes = list_chat_themes(state)
                    self.assertEqual([theme["id"] for theme in themes], ["windborne-adventure"])

                    manifest = get_chat_theme_manifest(state, "neon-night-city")
                    self.assertEqual(manifest["id"], "windborne-adventure")
                    self.assertEqual(manifest["tokens"]["global"]["themeColor"], "#f3cf57")

                    with self.assertRaises(FileNotFoundError):
                        set_active_chat_theme(state, {"id": "neon-night-city"})
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

    def test_save_chat_theme_clones_builtin_assets_without_builtin_ownership(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                summary = save_chat_theme(
                    state,
                    {
                        "baseId": "neon-night-city",
                        "manifest": {
                            "schema": 1,
                            "id": "my-neon",
                            "name": {"zh_CN": "我的霓虹"},
                            "tokens": {
                                "global": {"themeColor": "#ff66aa"},
                                "dialog": {"frameImage": "frame-dialog.svg"},
                            },
                        },
                    },
                )

                target = Path(tempdir) / "data" / "chat_ui_themes" / "my-neon"
                self.assertEqual(summary["id"], "my-neon")
                self.assertEqual(summary["source"], "user")
                self.assertTrue((target / "frame-dialog.svg").is_file())
                self.assertFalse((target / BUILTIN_THEME_OWNER_MARKER).exists())
                self.assertEqual(
                    get_chat_theme_manifest(state, "my-neon")["tokens"]["global"]["themeColor"],
                    "#ff66aa",
                )

                save_chat_theme(
                    state,
                    {
                        "baseId": "my-neon",
                        "manifest": {
                            "schema": 1,
                            "id": "my-neon",
                            "name": {"en": "Updated Neon"},
                            "tokens": {
                                "global": {"themeColor": "#33aaff"},
                                "dialog": {"frameImage": "frame-dialog.svg"},
                            },
                        },
                    },
                )
                self.assertTrue((target / "frame-dialog.svg").is_file())
                self.assertEqual(
                    get_chat_theme_manifest(state, "my-neon")["tokens"]["global"]["themeColor"],
                    "#33aaff",
                )
            finally:
                os.chdir(previous_cwd)

    def test_clone_save_rejects_a_concurrently_created_target(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                save_chat_theme(
                    state,
                    {
                        "baseId": "neon-night-city",
                        "manifest": {
                            "schema": 1,
                            "id": "shared-custom",
                            "name": {"en": "First clone"},
                            "tokens": {"global": {"themeColor": "#112233"}},
                        },
                    },
                )

                with self.assertRaises(FileExistsError):
                    save_chat_theme(
                        state,
                        {
                            "baseId": "sakura-dream",
                            "manifest": {
                                "schema": 1,
                                "id": "shared-custom",
                                "name": {"en": "Stale second clone"},
                                "tokens": {"global": {"themeColor": "#ffeeee"}},
                            },
                        },
                    )

                saved = get_chat_theme_manifest(state, "shared-custom")
                self.assertEqual(saved["name"]["en"], "First clone")
                self.assertEqual(saved["tokens"]["global"]["themeColor"], "#112233")
            finally:
                os.chdir(previous_cwd)

    def test_new_theme_publish_failure_leaves_no_partial_target(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                target = Path(tempdir) / "data" / "chat_ui_themes" / "atomic-custom"
                with patch("pathlib.Path.rename", side_effect=OSError("publish interrupted")):
                    with self.assertRaisesRegex(OSError, "publish interrupted"):
                        save_chat_theme(
                            state,
                            {
                                "baseId": "neon-night-city",
                                "manifest": {
                                    "schema": 1,
                                    "id": "atomic-custom",
                                    "name": {"en": "Atomic clone"},
                                    "tokens": {"dialog": {"frameImage": "frame-dialog.svg"}},
                                },
                            },
                        )

                self.assertFalse(target.exists())
            finally:
                os.chdir(previous_cwd)

    def test_save_chat_theme_rejects_builtin_overwrite(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                list_chat_themes(state)
                with self.assertRaises(PermissionError):
                    save_chat_theme(
                        state,
                        {
                            "baseId": "windborne-adventure",
                            "manifest": {
                                "schema": 1,
                                "id": "windborne-adventure",
                                "name": {"en": "Overwrite"},
                                "tokens": {},
                            },
                        },
                    )
            finally:
                os.chdir(previous_cwd)

    def test_save_chat_theme_rejects_path_components_in_theme_ids(self):
        state = self._make_state()
        previous_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as tempdir:
            os.chdir(tempdir)
            try:
                for theme_id in ("../escaped-theme", "nested/escaped-theme", "nested\\escaped-theme"):
                    with self.subTest(theme_id=theme_id), self.assertRaises(ValueError):
                        save_chat_theme(
                            state,
                            {
                                "baseId": "windborne-adventure",
                                "manifest": {
                                    "schema": 1,
                                    "id": theme_id,
                                    "name": {"en": "Escaped"},
                                    "tokens": {},
                                },
                            },
                        )

                with self.assertRaises(ValueError):
                    save_chat_theme(
                        state,
                        {
                            "baseId": "../windborne-adventure",
                            "manifest": {
                                "schema": 1,
                                "id": "escaped-theme",
                                "name": {"en": "Escaped"},
                                "tokens": {},
                            },
                        },
                    )

                themes_root = Path(tempdir) / "data" / "chat_ui_themes"
                self.assertFalse((Path(tempdir) / "data" / "escaped-theme").exists())
                self.assertFalse((themes_root / "nested").exists())
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
                with self.assertRaises(PermissionError):
                    delete_chat_theme(state, "sakura-dream")
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
                          "frameOutsetPx": -5,
                          "frameSlice": 500,
                          "frameWidthPx": 200,
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
                self.assertEqual(manifest["tokens"]["dialog"]["frameOutsetPx"], 0)
                self.assertEqual(manifest["tokens"]["dialog"]["frameSlice"], 200)
                self.assertEqual(manifest["tokens"]["dialog"]["frameWidthPx"], 96)
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
