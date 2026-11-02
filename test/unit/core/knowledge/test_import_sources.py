import json

import pytest

from core.knowledge import import_sources


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "gb18030"])
def test_txt_decoding_and_normalization(tmp_path, encoding):
    path = tmp_path / "notes.txt"
    path.write_bytes(" 第一行 \n\n第二行\n".encode(encoding))
    sources = import_sources.prepare_import_sources([path.name], source_root=tmp_path)
    assert [(s.name, s.kind, s.units) for s in sources] == [
        ("notes.txt", "txt", ("第一行", "第二行"))
    ]


def test_history_json_excludes_system_messages(tmp_path):
    path = tmp_path / "history.json"
    path.write_text(json.dumps([
        {"role": "system", "content": "secret prompt"},
        {"role": "user", "content": "remember tea"},
    ]), encoding="utf-8")
    source, = import_sources.prepare_import_sources([path], source_root=tmp_path)
    assert source.kind == "json"
    assert len(source.units) == 1
    assert "remember tea" in source.units[0]
    assert "secret prompt" not in source.units[0]


@pytest.mark.parametrize("name, content, error", [
    ("bad.json", "{bad", "JSON 历史消息格式无效"),
    ("empty.txt", " \n", "没有从文件中识别"),
    ("notes.csv", "text", "不支持的文件类型"),
])
def test_rejects_invalid_sources(tmp_path, name, content, error):
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        import_sources.prepare_import_sources([path], source_root=tmp_path)


def test_rejects_paths_outside_root(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    (tmp_path / "outside.txt").write_text("text", encoding="utf-8")
    with pytest.raises(ValueError, match="文件路径不允许"):
        import_sources.prepare_import_sources(["../outside.txt"], source_root=root)


def test_file_limits(tmp_path, monkeypatch):
    path = tmp_path / "notes.txt"
    path.write_bytes(b"1234")
    with pytest.raises(ValueError, match="至少选择"):
        import_sources.prepare_import_sources([], source_root=tmp_path)
    with pytest.raises(ValueError, match="最多导入"):
        import_sources.prepare_import_sources([path] * 51, source_root=tmp_path)
    monkeypatch.setattr(import_sources, "MAX_IMPORT_FILE_BYTES", 3)
    with pytest.raises(ValueError, match="文件过大"):
        import_sources.prepare_import_sources([path], source_root=tmp_path)
    monkeypatch.setattr(import_sources, "MAX_IMPORT_FILE_BYTES", 4)
    monkeypatch.setattr(import_sources, "MAX_IMPORT_TOTAL_BYTES", 7)
    with pytest.raises(ValueError, match="总大小"):
        import_sources.prepare_import_sources([path, path], source_root=tmp_path)
