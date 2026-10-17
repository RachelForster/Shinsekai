"""One authorized URL implementation for bridge and producer processes."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse


def append_query(url: str, params: dict[str, str]) -> str:
    pairs = [
        f"{quote(str(key), safe='')}={quote(str(value), safe='')}"
        for key, value in params.items()
        if str(value)
    ]
    if not pairs:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{'&'.join(pairs)}"


@dataclass(frozen=True, slots=True)
class BridgeResourceUrls:
    http_base: str
    auth_token: str = ""
    approve_media_path: Callable[[str], object] | None = None

    @classmethod
    def from_producer_endpoint(cls, endpoint: str) -> "BridgeResourceUrls":
        parsed = urlparse(endpoint)
        host = parsed.hostname or "127.0.0.1"
        if ":" in host:
            host = f"[{host}]"
        port = parsed.port or 0
        query = parse_qs(parsed.query)
        token = (
            query.get("shinsekai_bridge_token") or query.get("token") or [""]
        )[0].strip()
        return cls(f"http://{host}:{port - 1 if port else port}", token)

    def _url(self, route: str) -> str:
        return append_query(
            f"{self.http_base}{route}", {"shinsekai_bridge_token": self.auth_token}
        )

    def media_url(self, raw_path: str) -> str:
        path = str(raw_path or "").strip()
        if not path or path.startswith(
            ("http://", "https://", "blob:", "data:", "/assets/")
        ):
            return path
        if self.approve_media_path is not None:
            self.approve_media_path(path)
        return self._url(f"/api/media?path={quote(path)}")

    def avatar_url(self, model_path: str, path: str) -> str:
        relative = (
            Path(path).resolve().relative_to(Path(model_path).resolve().parent).as_posix()
        )
        return self._url(
            f"/api/avatar/file?model_path={quote(model_path)}&path={quote(relative)}"
        )
