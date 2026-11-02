"""Serialize model selection and synthesis across desktop/chat processes."""

from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile
import uuid

from filelock import FileLock


@contextmanager
def tts_model_session(adapter, endpoint: str, *, timeout: float = 120):
    actual_endpoint = getattr(adapter, "tts_server_url", None)
    if isinstance(actual_endpoint, str) and actual_endpoint:
        endpoint = actual_endpoint
    directory = Path(tempfile.gettempdir()) / "shinsekai-tts-locks"
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(endpoint.rstrip("/").encode()).hexdigest()
    owner_file = directory / f"{key}.owner"
    with FileLock(str(directory / f"{key}.lock"), timeout=timeout):
        owner = getattr(adapter, "_shinsekai_tts_owner", None)
        if not isinstance(owner, str):
            owner = uuid.uuid4().hex
            adapter._shinsekai_tts_owner = owner
        previous = owner_file.read_text() if owner_file.exists() else ""
        if previous != owner:
            # GPT-SoVITS caches server model paths in each adapter. Another process
            # may have changed the server since this adapter last synthesized.
            for field in (
                "gpt_model_path",
                "sovits_model_path",
                "loaded_character_name",
            ):
                if hasattr(adapter, field):
                    setattr(adapter, field, None)
        owner_file.write_text(owner)
        yield
