"""Thin LLM tool wrappers around host filesystem services."""

from __future__ import annotations

from typing import Any

from core.media.file_operations import (
    append_text_file,
    copy_file,
    create_directory,
    delete_path,
    extract_archive,
    inspect_path,
    list_directory,
    move_path,
    open_local_path,
    read_text_file,
    search_file_content,
    search_files,
    write_text_file,
)
from sdk.tool_registry import tool


@tool(
    name="file_search",
    group="file",
    description=(
        "Search for files by name pattern or extension in a directory. "
        "pattern: glob like '*.py' or 'report*'. dir_path: directory to search "
        "(default home). Returns up to 50 matches with size and path."
    ),
)
def file_search(pattern: str, dir_path: str = "~") -> dict[str, Any]:
    return search_files(pattern, dir_path)


@tool(
    name="file_list_dir",
    group="file",
    description=(
        "List contents of a directory. path: directory path "
        "(default current working dir). Returns files and subdirectories with sizes."
    ),
)
def file_list_dir(path: str = ".") -> dict[str, Any]:
    return list_directory(path)


@tool(
    name="file_read",
    group="file",
    description=(
        "Read a text file and return its content. path: file path. "
        "max_chars: max characters to read (default 5000, for preview). "
        "line_start/line_end: optional line range (1-indexed)."
    ),
)
def file_read(
    path: str,
    max_chars: int = 5000,
    line_start: int = 0,
    line_end: int = 0,
) -> dict[str, Any]:
    return read_text_file(
        path,
        max_chars=max_chars,
        line_start=line_start,
        line_end=line_end,
    )


@tool(
    name="file_info",
    group="file",
    description=(
        "Get detailed info about a file or directory: size, modified time, type."
    ),
)
def file_info(path: str) -> dict[str, Any]:
    return inspect_path(path)


@tool(
    name="file_open",
    group="file",
    description="Open a file or folder with the default system application.",
)
def file_open(path: str) -> dict[str, Any]:
    return open_local_path(path)


@tool(
    name="file_search_content",
    group="file",
    description=(
        "Search for text inside files. keyword: text to search. "
        "dir_path: directory. file_pattern: optional glob filter like '*.py'. "
        "Returns matching lines with file paths."
    ),
)
def file_search_content(
    keyword: str,
    dir_path: str = "~",
    file_pattern: str = "*",
) -> dict[str, Any]:
    return search_file_content(
        keyword,
        directory=dir_path,
        file_pattern=file_pattern,
    )


@tool(
    name="file_move",
    group="file",
    risk="high",
    description=(
        "Move or rename a file/directory. source: original path. "
        "dest: destination path."
    ),
)
def file_move(source: str, dest: str) -> dict[str, Any]:
    return move_path(source, dest)


@tool(
    name="file_copy",
    group="file",
    risk="medium",
    description="Copy a file. source: original path. dest: destination path.",
)
def file_copy(source: str, dest: str) -> dict[str, Any]:
    return copy_file(source, dest)


@tool(
    name="file_delete",
    group="file",
    risk="high",
    description=(
        "Delete a file or empty directory. WARNING: this is permanent. "
        "Returns what was deleted."
    ),
)
def file_delete(path: str) -> dict[str, Any]:
    return delete_path(path)


@tool(
    name="file_extract",
    group="file",
    description=(
        "Extract a zip or tar.gz archive to a directory. "
        "archive_path: the compressed file. extract_to: target directory "
        "(defaults to same folder)."
    ),
)
def file_extract(archive_path: str, extract_to: str = "") -> dict[str, Any]:
    return extract_archive(archive_path, destination=extract_to)


@tool(
    name="file_write",
    group="file",
    risk="high",
    description=(
        "Create a new file or overwrite an existing file with text content. "
        "path: file path. content: text content to write."
    ),
)
def file_write(path: str, content: str) -> dict[str, Any]:
    return write_text_file(path, content)


@tool(
    name="file_append",
    group="file",
    risk="medium",
    description=(
        "Append text to an existing file. Creates the file if it doesn't exist. "
        "path: file path. content: text to append."
    ),
)
def file_append(path: str, content: str) -> dict[str, Any]:
    return append_text_file(path, content)


@tool(
    name="file_mkdir",
    group="file",
    risk="medium",
    description=(
        "Create a new directory (and any missing parent directories). "
        "path: directory path to create."
    ),
)
def file_mkdir(path: str) -> dict[str, Any]:
    return create_directory(path)
