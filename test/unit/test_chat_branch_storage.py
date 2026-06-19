import json
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.sprite.chat_branch_storage import (
    ACTIVE_HISTORY_FILENAME,
    BRANCH_TREE_FILENAME,
    chat_history_active_path,
    chat_history_branch_tree_path,
    load_branch_state,
    remove_chat_history_storage,
    save_branch_state,
)
from frontend_bridge_core.chat import _chat_history_path
from frontend_bridge_core.templates import _latest_history_json


class ChatBranchStorageTests(unittest.TestCase):
    def test_non_existing_json_path_maps_to_session_folder(self):
        path = Path("data/chat_history/session.json")

        self.assertEqual(chat_history_active_path(path), Path("data/chat_history/session") / ACTIVE_HISTORY_FILENAME)
        self.assertEqual(chat_history_branch_tree_path(path), Path("data/chat_history/session") / BRANCH_TREE_FILENAME)

    def test_existing_json_file_stays_legacy_history(self):
        with self.subTest("legacy"):
            root = Path("data/chat_history/test-legacy")
            root.mkdir(parents=True, exist_ok=True)
            path = root / "session.json"
            path.write_text("[]", encoding="utf-8")
            try:
                self.assertEqual(chat_history_active_path(path), path)
            finally:
                remove_chat_history_storage(path)
                try:
                    root.rmdir()
                except OSError:
                    pass

    def test_saves_and_loads_branch_tree_under_session_folder(self):
        root = Path("data/chat_history/test-branch-tree")
        remove_chat_history_storage(root)
        branch_state = {
            "active": "branch-2",
            "counter": 2,
            "branches": {
                "main": {
                    "id": "main",
                    "label": "主线",
                    "parentId": None,
                    "history": ["Mio: Ready"],
                    "messages": [{"role": "assistant", "content": "Ready"}],
                },
                "branch-2": {
                    "id": "branch-2",
                    "label": "七海路线",
                    "parentId": "main",
                    "history": ["你: hello"],
                    "messages": [{"role": "user", "content": "hello"}],
                },
            },
        }
        try:
            tree_path = save_branch_state(root, branch_state)
            restored = load_branch_state(root)

            self.assertEqual(tree_path, root / BRANCH_TREE_FILENAME)
            self.assertEqual(restored["active"], "branch-2")
            self.assertEqual(restored["branches"]["branch-2"]["label"], "七海路线")
            self.assertEqual(restored["branches"]["branch-2"]["messages"][0]["content"], "hello")
        finally:
            remove_chat_history_storage(root)

    def test_latest_history_finds_directory_sessions_and_legacy_files(self):
        root = Path("data/chat_history/test-latest")
        remove_chat_history_storage(root)
        root.mkdir(parents=True, exist_ok=True)
        legacy = root / "legacy.json"
        session = root / "session"
        session.mkdir()
        try:
            legacy.write_text("[]", encoding="utf-8")
            time.sleep(0.01)
            (session / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")
            (session / BRANCH_TREE_FILENAME).write_text(json.dumps({"branches": []}), encoding="utf-8")

            self.assertEqual(_latest_history_json(root.as_posix()), session)
        finally:
            remove_chat_history_storage(root)

    def test_bridge_history_path_prefers_session_directories_for_new_paths(self):
        root = Path("data/chat_history/test-bridge-path")
        remove_chat_history_storage(root)
        root.mkdir(parents=True, exist_ok=True)
        state = SimpleNamespace(history_dir=root.as_posix())
        template = {"scenario": "scene", "system": "system"}
        try:
            default_path = _chat_history_path(state, {"historyPath": ""}, template)
            explicit_path = _chat_history_path(state, {"historyPath": (root / "manual.json").as_posix()}, template)
            legacy_path = root / "legacy.json"
            legacy_path.write_text("[]", encoding="utf-8")

            self.assertEqual(default_path.parent, root.resolve())
            self.assertEqual(default_path.suffix, "")
            self.assertEqual(explicit_path, root.resolve() / "manual")
            self.assertEqual(_chat_history_path(state, {"historyPath": legacy_path.as_posix()}, template), legacy_path.resolve())
        finally:
            remove_chat_history_storage(root)


if __name__ == "__main__":
    unittest.main()
