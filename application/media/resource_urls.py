"""Resource addressing port, independent of event delivery and model formats."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class ResourceUrls(Protocol):
    def media_url(self, path: str) -> str: ...

    def avatar_url(self, model_path: str, path: str) -> str: ...


class UnconfiguredResourceUrls:
    """Keep legacy local images usable before a transport is composed."""

    def media_url(self, path: str) -> str:
        return str(path or "")

    def avatar_url(self, model_path: str, path: str) -> str:
        raise RuntimeError("Model resource URLs must be configured before presentation")
