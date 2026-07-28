from ai.tools import file_tools


def test_file_write_delegates_to_media_service(monkeypatch) -> None:
    expected = {
        "written": "/tmp/example.txt",
        "size": 7,
        "existed": False,
    }
    calls: list[tuple[str, str]] = []

    def fake_write(path: str, content: str):
        calls.append((path, content))
        return expected

    monkeypatch.setattr(file_tools, "write_text_file", fake_write)

    assert file_tools.file_write("example.txt", "content") == expected
    assert calls == [("example.txt", "content")]
