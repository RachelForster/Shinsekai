from __future__ import annotations

import json
import zipfile

from frontend_bridge_core.logs import _diagnostic_bundle, _log_file_list, _log_snapshot


def test_log_snapshot_parses_jsonl_entries(tmp_path):
    path = tmp_path / "logs" / "chat" / "run.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                json.dumps({"level": "INFO", "logger": "demo", "message": "started"}, ensure_ascii=False),
                "plain text line",
                json.dumps({"event": "task.done", "task_id": "task-1"}, ensure_ascii=False),
            ]
        ),
        encoding="utf-8",
    )

    snapshot = _log_snapshot(path)

    assert snapshot["name"] == "run.jsonl"
    assert len(snapshot["entries"]) == 2
    assert snapshot["entries"][0]["line"] == 1
    assert snapshot["entries"][1]["event"] == "task.done"


def test_log_file_list_returns_recent_project_logs(tmp_path):
    older = tmp_path / "logs" / "chat" / "older.log"
    newer = tmp_path / "logs" / "frontend-bridge" / "newer.jsonl"
    older.parent.mkdir(parents=True)
    newer.parent.mkdir(parents=True)
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")

    result = _log_file_list(tmp_path)

    names = [item["name"] for item in result["files"]]
    assert "newer.jsonl" in names
    assert "older.log" in names
    assert result["files"][0]["relativePath"].startswith("logs/")


def test_diagnostic_bundle_contains_manifest_and_logs(tmp_path):
    log_path = tmp_path / "logs" / "chat" / "run.jsonl"
    log_path.parent.mkdir(parents=True)
    log_path.write_text('{"level":"INFO","message":"ok"}\n', encoding="utf-8")
    (tmp_path / "VERSION").write_text("1.2.3", encoding="utf-8")

    result = _diagnostic_bundle(tmp_path)

    archive_path = tmp_path / result["path"]
    assert archive_path.is_file()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "logs/chat/run.jsonl" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["runtime"]["python_version"]
        assert manifest["runtime"]["project_root"] == tmp_path.as_posix()
        assert isinstance(manifest["runtime"]["gpus"], list)
        assert manifest["runtime"]["gpu_count"] == len(manifest["runtime"]["gpus"])
