import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import core.sprite.chat_branch_storage as chat_branch_storage
from core.sprite.chat_branch_storage import (
    ACTIVE_HISTORY_FILENAME,
    BRANCH_TREE_FILENAME,
    chat_history_active_path,
    chat_history_branch_tree_path,
    load_branch_state,
    reconcile_active_branch_state,
    remove_chat_history_storage,
    save_branch_state,
)
from sdk.path_contract import project_root
from application.chat.runtime_process import _chat_history_path
from application.chat.templates import _latest_history_json


class ChatBranchStorageTests(unittest.TestCase):
    def test_reconcile_prefers_recovered_active_history_over_stale_branch_payload(self):
        branch_state = {
            "active": "main",
            "branches": {
                "main": {
                    "id": "main",
                    "history": ["Mio: stale"],
                    "messages": [{"role": "assistant", "content": "stale"}],
                }
            },
        }
        recovered_messages = [
            {"role": "user", "content": "latest question"},
            {"role": "assistant", "content": "latest answer"},
        ]
        recovered_history = ["Aoi: latest question", "Mio: latest answer"]

        messages, history = reconcile_active_branch_state(
            branch_state,
            recovered_messages,
            recovered_history,
        )

        self.assertEqual(messages, recovered_messages)
        self.assertEqual(history, recovered_history)
        self.assertEqual(branch_state["branches"]["main"]["messages"], recovered_messages)
        self.assertEqual(branch_state["branches"]["main"]["history"], recovered_history)

    def test_reconcile_uses_branch_payload_when_active_history_is_empty(self):
        branch_messages = [{"role": "assistant", "content": "restored"}]
        branch_history = ["Mio: restored"]
        branch_state = {
            "active": "branch-2",
            "branches": {
                "branch-2": {
                    "id": "branch-2",
                    "history": branch_history,
                    "messages": branch_messages,
                }
            },
        }

        messages, history = reconcile_active_branch_state(branch_state, [], [])

        self.assertEqual(messages, branch_messages)
        self.assertEqual(history, branch_history)

    def test_reconcile_respects_an_existing_empty_active_history(self):
        branch_state = {
            "active": "main",
            "branches": {
                "main": {
                    "id": "main",
                    "history": ["Mio: stale"],
                    "messages": [{"role": "assistant", "content": "stale"}],
                }
            },
        }

        messages, history = reconcile_active_branch_state(
            branch_state,
            [],
            [],
            active_history_present=True,
        )

        self.assertEqual(messages, [])
        self.assertEqual(history, [])
        self.assertEqual(branch_state["branches"]["main"]["messages"], [])
        self.assertEqual(branch_state["branches"]["main"]["history"], [])

    def test_cleanup_reports_locked_branch_metadata_without_removing_active(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "session"
            root.mkdir()
            active = root / ACTIVE_HISTORY_FILENAME
            branches = root / BRANCH_TREE_FILENAME
            active.write_text("[]", encoding="utf-8")
            branches.write_text("{}", encoding="utf-8")
            original_remove = chat_branch_storage.remove_file_without_links

            def fail_locked_branches(path: Path, *args, **kwargs):
                if path == branches:
                    raise PermissionError("branches.json is locked")
                return original_remove(path, *args, **kwargs)

            with patch.object(
                chat_branch_storage,
                "remove_file_without_links",
                fail_locked_branches,
            ):
                with self.assertRaisesRegex(PermissionError, "locked"):
                    remove_chat_history_storage(root)

            self.assertTrue(active.is_file())
            self.assertTrue(branches.is_file())

    def test_managed_cleanup_reports_locked_metadata_without_removing_active(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            collection = Path(tmp_dir) / "chat-history"
            session = collection / "session"
            session.mkdir(parents=True)
            active = session / ACTIVE_HISTORY_FILENAME
            branches = session / BRANCH_TREE_FILENAME
            active.write_text("[]", encoding="utf-8")
            branches.write_text("{}", encoding="utf-8")
            original_remove = chat_branch_storage.remove_file_without_links

            def fail_locked_branches(path: Path, *args, **kwargs):
                if path == branches:
                    raise PermissionError("branches.json is locked")
                return original_remove(path, *args, **kwargs)

            with patch.object(
                chat_branch_storage,
                "remove_file_without_links",
                fail_locked_branches,
            ):
                with self.assertRaisesRegex(PermissionError, "locked"):
                    remove_chat_history_storage(session, root=collection)

            self.assertTrue(active.is_file())
            self.assertTrue(branches.is_file())

    def test_managed_cleanup_preserves_unrelated_session_content(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            collection = Path(tmp_dir) / "chat-history"
            session = collection / "session"
            session.mkdir(parents=True)
            (session / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")
            (session / BRANCH_TREE_FILENAME).write_text("{}", encoding="utf-8")
            marker = session / "user-owned.txt"
            marker.write_text("keep", encoding="utf-8")

            remove_chat_history_storage(session, root=collection)

            self.assertFalse((session / ACTIVE_HISTORY_FILENAME).exists())
            self.assertFalse((session / BRANCH_TREE_FILENAME).exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_non_existing_json_path_maps_to_session_folder(self):
        path = Path("data/chat_history/session.json")
        expected = project_root() / "data/chat_history/session"

        self.assertEqual(chat_history_active_path(path), expected / ACTIVE_HISTORY_FILENAME)
        self.assertEqual(chat_history_branch_tree_path(path), expected / BRANCH_TREE_FILENAME)

    def test_relative_history_helpers_use_project_root_instead_of_process_cwd(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            project = base / "project"
            unrelated_cwd = base / "unrelated-cwd"
            project.mkdir()
            unrelated_cwd.mkdir()
            previous_cwd = Path.cwd()
            try:
                with patch.dict(
                    os.environ,
                    {"SHINSEKAI_PROJECT_ROOT": project.as_posix()},
                ):
                    os.chdir(unrelated_cwd)
                    result = chat_history_active_path("data/chat_history/session.json")
            finally:
                os.chdir(previous_cwd)

        self.assertEqual(
            result,
            project / "data/chat_history/session" / ACTIVE_HISTORY_FILENAME,
        )

    def test_history_storage_helpers_reject_lexical_aliases_before_path_construction(self):
        for path in (
            "data/chat_history/./session.json",
            "data/chat_history//session.json",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                chat_history_active_path(path)

    def test_history_storage_helpers_reject_linked_session_path(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            project = base / "project"
            external = base / "external"
            history = project / "data/chat_history"
            history.mkdir(parents=True)
            external.mkdir()
            (external / "active.json").write_text("[]", encoding="utf-8")
            alias = history / "session"
            try:
                alias.symlink_to(external, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")

            with patch.dict(
                os.environ,
                {"SHINSEKAI_PROJECT_ROOT": project.as_posix()},
            ):
                with self.assertRaises(PermissionError):
                    chat_history_active_path("data/chat_history/session")

    def test_existing_json_file_stays_legacy_history(self):
        with self.subTest("legacy"):
            root = Path("data/chat_history/test-legacy")
            root.mkdir(parents=True, exist_ok=True)
            path = root / "session.json"
            path.write_text("[]", encoding="utf-8")
            try:
                self.assertEqual(chat_history_active_path(path), path.resolve())
            finally:
                remove_chat_history_storage(path)
                try:
                    root.rmdir()
                except OSError:
                    pass

    def test_removing_legacy_file_preserves_unrelated_same_named_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "chat-history"
            root.mkdir()
            legacy = root / "session.json"
            unrelated = root / "session"
            legacy.write_text("[]", encoding="utf-8")
            unrelated.mkdir()
            marker = unrelated / "user-owned.txt"
            marker.write_text("keep", encoding="utf-8")

            remove_chat_history_storage(legacy, root=root)

            self.assertFalse(legacy.exists())
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_history_removal_preserves_replacement_file_identity(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "chat-history"
            target = root / "session.json"
            preserved = root / "session-preserved.json"
            root.mkdir()
            target.write_text("original", encoding="utf-8")
            real_remove = chat_branch_storage.remove_file_without_links

            def replace_before_remove(path, **kwargs):
                target.rename(preserved)
                target.write_text("peer", encoding="utf-8")
                return real_remove(path, **kwargs)

            with patch.object(
                chat_branch_storage,
                "remove_file_without_links",
                replace_before_remove,
            ):
                with self.assertRaises(PermissionError):
                    remove_chat_history_storage(target, root=root)

            self.assertEqual(target.read_text(encoding="utf-8"), "peer")
            self.assertEqual(preserved.read_text(encoding="utf-8"), "original")

    def test_removal_boundary_rejects_collection_root_and_external_target(self):
        root = Path("data/chat_history/test-removal-boundary").resolve()
        remove_chat_history_storage(root)
        root.mkdir(parents=True)
        outside = root.parent / "must-survive.json"
        outside.write_text("[]", encoding="utf-8")
        root_active = root / ACTIVE_HISTORY_FILENAME
        root_active.write_text("[]", encoding="utf-8")
        try:
            with self.assertRaises(PermissionError):
                remove_chat_history_storage(root, root=root)
            with self.assertRaises(PermissionError):
                remove_chat_history_storage(root_active, root=root)
            with self.assertRaises(PermissionError):
                remove_chat_history_storage(outside, root=root)
            self.assertTrue(root_active.is_file())
            self.assertTrue(outside.is_file())
        finally:
            outside.unlink(missing_ok=True)
            remove_chat_history_storage(root)

    def test_removal_boundary_rejects_internal_directory_alias(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "chat-history"
            real_parent = root / "real-parent"
            real_session = real_parent / "session"
            real_session.mkdir(parents=True)
            marker = real_session / ACTIVE_HISTORY_FILENAME
            marker.write_text("[]", encoding="utf-8")
            alias = root / "alias"
            try:
                alias.symlink_to(real_parent, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symbolic links are unavailable")

            with self.assertRaises(PermissionError):
                remove_chat_history_storage(alias / "session", root=root)

            self.assertEqual(marker.read_text(encoding="utf-8"), "[]")

    def test_removal_boundary_rejects_lexical_alias_before_path_construction(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "chat-history"
            session = root / "session"
            session.mkdir(parents=True)
            marker = session / ACTIVE_HISTORY_FILENAME
            marker.write_text("[]", encoding="utf-8")

            for aliased in (
                f"{root.as_posix()}/./session",
                f"{root.as_posix()}//session",
            ):
                with self.assertRaises(ValueError):
                    remove_chat_history_storage(aliased, root=root)

            self.assertEqual(marker.read_text(encoding="utf-8"), "[]")

    def test_relative_removal_target_is_anchored_to_history_root_not_cwd(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            base = Path(temporary_directory)
            root = base / "chat-history"
            unrelated_cwd = base / "unrelated-cwd"
            session = root / "session"
            session.mkdir(parents=True)
            unrelated_cwd.mkdir()
            (session / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")

            previous_cwd = Path.cwd()
            try:
                os.chdir(unrelated_cwd)
                remove_chat_history_storage("session", root=root)
            finally:
                os.chdir(previous_cwd)

            self.assertFalse(session.exists())

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
                    "messages": [{
                        "role": "user",
                        "content": "hello",
                        "input_text": "hello",
                        "attachments": [{"kind": "image", "name": "scene.png", "path": "C:/scene.png"}],
                    }],
                },
            },
        }
        try:
            tree_path = save_branch_state(root, branch_state)
            restored = load_branch_state(root)

            self.assertEqual(tree_path, root.resolve() / BRANCH_TREE_FILENAME)
            self.assertEqual(restored["active"], "branch-2")
            self.assertEqual(restored["branches"]["branch-2"]["label"], "七海路线")
            self.assertEqual(restored["branches"]["branch-2"]["messages"][0]["content"], "hello")
            self.assertEqual(restored["branches"]["branch-2"]["messages"][0]["input_text"], "hello")
            self.assertEqual(
                restored["branches"]["branch-2"]["messages"][0]["attachments"][0]["name"],
                "scene.png",
            )
        finally:
            remove_chat_history_storage(root)

    def test_branch_tree_publish_failure_preserves_previous_file(self):
        root = Path("data/chat_history/test-branch-atomic")
        remove_chat_history_storage(root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            original = {
                "active": "main",
                "counter": 1,
                "branches": {"main": {"id": "main"}},
            }
            save_branch_state(root, original)
            tree = root / BRANCH_TREE_FILENAME
            previous = tree.read_text(encoding="utf-8")
            with patch(
                "core.sprite.chat_branch_storage.atomic_write_text",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaisesRegex(OSError, "disk full"):
                    save_branch_state(
                        root,
                        {
                            "active": "other",
                            "counter": 2,
                            "branches": {"other": {"id": "other"}},
                        },
                    )
            self.assertEqual(tree.read_text(encoding="utf-8"), previous)
        finally:
            remove_chat_history_storage(root)

    def test_latest_history_finds_directory_sessions_and_legacy_files(self):
        root = Path("data/chat_history/test-latest")
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        legacy = root / "legacy.json"
        session = root / "session"
        session.mkdir()
        try:
            legacy.write_text("[]", encoding="utf-8")
            time.sleep(0.01)
            (session / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")
            (session / BRANCH_TREE_FILENAME).write_text(json.dumps({"branches": []}), encoding="utf-8")

            self.assertEqual(_latest_history_json(root.as_posix()), session.resolve())
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_latest_history_ignores_reserved_root_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            root = project / "chat-history"
            session = root / "valid-session"
            session.mkdir(parents=True)
            (session / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")
            time.sleep(0.01)
            (root / ACTIVE_HISTORY_FILENAME).write_text("[]", encoding="utf-8")
            (root / BRANCH_TREE_FILENAME).write_text("{}", encoding="utf-8")

            self.assertEqual(
                _latest_history_json(
                    "chat-history",
                    project_root=project,
                ),
                session.resolve(),
            )

    def test_latest_history_ignores_root_level_legacy_temp_fragment(self):
        root = Path("data/chat_history/test-latest-temp-fragment")
        remove_chat_history_storage(root)
        root.mkdir(parents=True, exist_ok=True)
        fragment = root / "orphan.json.tmp"
        fragment.write_text("[]", encoding="utf-8")
        try:
            self.assertIsNone(_latest_history_json(root.as_posix()))
        finally:
            remove_chat_history_storage(root)

    def test_latest_history_rejects_directory_outside_explicit_project_root(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project = base / "project"
            outside = base / "outside"
            project.mkdir()
            outside.mkdir()
            (outside / "session.json").write_text("[]", encoding="utf-8")

            with self.assertRaises(PermissionError):
                _latest_history_json(
                    outside.as_posix(),
                    project_root=project,
                )

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
