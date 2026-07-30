from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import default as default_email_policy
from pathlib import Path
from typing import BinaryIO, Callable

from sdk.path_utils import safe_child_path, safe_filename


@dataclass(slots=True)
class UploadedFiles:
    root: Path
    paths: tuple[Path, ...]
    _owns_cleanup: bool = field(default=True, init=False, repr=False)

    def cleanup(self) -> None:
        if not self._owns_cleanup:
            return
        self._owns_cleanup = False
        shutil.rmtree(self.root, ignore_errors=True)

    def transfer_cleanup(self) -> Callable[[], None]:
        if not self._owns_cleanup:
            raise RuntimeError(
                "uploaded files cleanup ownership was already transferred"
            )
        self._owns_cleanup = False
        root = self.root
        return lambda: shutil.rmtree(root, ignore_errors=True)


def read_uploaded_files(
    content_type: str,
    content_length: str,
    stream: BinaryIO,
) -> UploadedFiles:
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("request must be multipart/form-data")
    length = int(content_length or "0")
    if length <= 0:
        raise ValueError("request body is empty")

    temp_dir = Path(tempfile.mkdtemp(prefix="shinsekai-frontend-upload-"))
    try:
        body = stream.read(length)
        headers = (f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n").encode(
            "utf-8"
        )
        message = BytesParser(policy=default_email_policy).parsebytes(headers + body)
        paths: list[Path] = []
        for part in message.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue
            if part.get_param("name", header="content-disposition") != "files":
                continue
            try:
                filename = safe_filename(str(part.get_filename() or ""))
            except ValueError:
                continue
            destination = safe_child_path(temp_dir, filename)
            destination.write_bytes(part.get_payload(decode=True) or b"")
            paths.append(destination)
        if not paths:
            raise ValueError("no files uploaded")
        return UploadedFiles(root=temp_dir, paths=tuple(paths))
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
