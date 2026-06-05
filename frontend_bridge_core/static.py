from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

from .state import BridgeState


def _frontend_dist_root(state: BridgeState) -> Path | None:
    raw = str(state.frontend_dist_dir or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def _schedule_browser_open(url: str) -> None:
    def _open() -> None:
        try:
            webbrowser.open(url)
        except Exception as exc:
            print(f"Could not open browser automatically: {exc}")

    timer = threading.Timer(0.35, _open)
    timer.daemon = True
    timer.start()
