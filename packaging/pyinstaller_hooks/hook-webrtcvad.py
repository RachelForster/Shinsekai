# PyInstaller: 覆盖 _pyinstaller_hooks_contrib 自带 hook
# 官方 hook 会 copy_metadata("webrtcvad")，在 conda/无 wheel 元数据 的安装上会抛
# importlib.metadata.PackageNotFoundError，导致 main_sprite 分析失败。

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

logger = logging.getLogger(__name__)

datas: list = []


def _from_origin() -> list[tuple[str, str]]:
    sp = importlib.util.find_spec("webrtcvad")
    if sp is None or not sp.origin:
        return []
    p = Path(sp.origin)
    if p.suffix.lower() in (".pyd", ".so", ".dylib") and p.is_file():
        return [(str(p), ".")]
    return []


try:
    binaries = collect_dynamic_libs("webrtcvad")
except Exception as e:  # noqa: BLE001
    logger.warning("hook-webrtcvad: collect_dynamic_libs failed (%s), falling back to origin", e)
    binaries = _from_origin()
else:
    if not binaries:
        binaries = _from_origin()

hiddenimports = ["webrtcvad"]
