"""设置界面小工具。"""

from __future__ import annotations


class PathFile:
    """与 Gradio 文件对象相同，供 character_manager / background_manager 使用 .name 字段。"""

    __slots__ = ("name",)

    def __init__(self, path: str) -> None:
        self.name = path


def path_file_list(paths: list[str]) -> list[PathFile]:
    return [PathFile(p) for p in paths if p]
