"""Pinned, verified ToonOut artifacts shared by setup and the isolated worker."""

import hashlib
from functools import lru_cache
from pathlib import Path

from core.paths import project_root


MODEL_REVISION = "cbf720eca394edcde66b861a8a8c20fbabe9c748"
ARCH_REVISION = "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4"
ARTIFACTS = {
    "birefnet_finetuned_toonout.pth": (
        f"joelseytre/toonout/resolve/{MODEL_REVISION}/birefnet_finetuned_toonout.pth",
        "8c7f8a0bc24400f4caade76622f75ff22ca1e93e169add9d2b70093e2487fbe5",
    ),
    "birefnet.py": (
        f"ZhengPeng7/BiRefNet/resolve/{ARCH_REVISION}/birefnet.py",
        "208771ae626f653d64128fbf2d6ac9f8e645c5cc5e286258a73ec3322bbfe5ef",
    ),
    "BiRefNet_config.py": (
        f"ZhengPeng7/BiRefNet/resolve/{ARCH_REVISION}/BiRefNet_config.py",
        "e7b8c2a74f6cea6a59553d517f71d47f2c1d90e670a13416af17c25fe2f3dc52",
    ),
}


def model_directory():
    return project_root() / "cache" / "models" / "toonout"


@lru_cache(maxsize=16)
def _verified(path, mtime_ns, size, expected):
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == expected


def verify_assets(directory):
    for name, (_, expected) in ARTIFACTS.items():
        path = Path(directory) / name
        stat = path.stat()
        if not _verified(str(path.resolve()), stat.st_mtime_ns, stat.st_size, expected):
            raise ValueError(f"ToonOut 文件校验失败：{name}，请重新运行安装命令")


def install_assets(directory):
    from core.downloads import download_archive

    directory = Path(directory)
    for name, (remote, expected) in ARTIFACTS.items():
        path = directory / name
        if path.exists():
            stat = path.stat()
            if _verified(str(path.resolve()), stat.st_mtime_ns, stat.st_size, expected):
                continue
        print(f"Downloading ToonOut: {name}", flush=True)
        download_archive(
            f"https://huggingface.co/{remote}", path, {}, expected_sha256=expected
        )
    verify_assets(directory)
