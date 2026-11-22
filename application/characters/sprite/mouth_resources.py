"""Optional recognition runtime and verified model resources for sprite mouths."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Any, Iterable

from application.media.resource_paths import MediaResourcePaths
from application.runtime.tasks import _update_task
from sdk.path_utils import reject_control_chars, safe_child_path, safe_existing_file_path

MODEL_FILES = {
    "yolov3": {
        "repo": "hysts/anime-face-detector-yolov3",
        "revision": "afdd4226a79ae8bb81f334dbcffd34f8cc000c38",
        "size": 246354512,
        "sha256": "23bbc708146bcbc1c910f00fe152adbc70d7658d875a0121eaf4ee61d978b2c4",
    },
    "hrnetv2": {
        "repo": "hysts/anime-face-detector-hrnetv2",
        "revision": "9b3435248b26aeb82e2a8578fe9d86d5d57158af",
        "size": 38917560,
        "sha256": "e71271376406a743c01528a0460637fcc06e72aeeea583f85007cc72dc8b7a4a",
    },
}
MODULES = {
    "torch": "torch",
    "torchvision": "torchvision",
    "numpy": "numpy>=1.26.4",
    "cv2": "opencv-python-headless>=4.10,<5",
    "anime_face_detector": "anime-face-detector==0.1.0",
    "huggingface_hub": "huggingface-hub>=0.30",
    "safetensors": "safetensors>=0.5.3",
    "av": "av>=14",
    "PIL": "Pillow>=10",
}
_SETUP_LOCK = threading.Lock()


def _local_file_access_roots(state: Any) -> tuple[Path, ...]:
    project_root = Path(getattr(state, "project_root_dir", "") or Path.cwd())
    return MediaResourcePaths(project_root).file_access_roots


def _resolve_file_access_roots(
    state: Any, file_access_roots: Iterable[Path] = ()
) -> tuple[Path, ...]:
    roots = tuple(file_access_roots)
    if not roots:
        return _local_file_access_roots(state)
    project_root = Path(getattr(state, "project_root_dir", "") or Path.cwd())
    return MediaResourcePaths(
        project_root, file_access_roots=roots
    ).file_access_roots


def locations(root):
    root = Path(root).resolve()
    return {
        "models": safe_child_path(root, "data/models/sprite-mouth"),
        "packages": safe_child_path(root, "data/runtime/sprite-mouth/packages"),
        "settings": safe_child_path(root, "data/config/sprite-mouth.json"),
    }


def package_directory(root, version):
    return locations(root)["packages"] / f"python-{version[0]}.{version[1]}"


def settings(root):
    path = locations(root)["settings"]
    if not path.is_file():
        return {"pythonPath": "", "device": "auto"}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("device", "auto") not in {"auto", "cpu", "cuda"}:
        raise ValueError("口型识别环境配置无效")
    return {"pythonPath": str(data.get("pythonPath") or ""), "device": data.get("device", "auto")}


def configure(root, payload):
    previous = settings(root)
    device = payload.get("device", previous["device"])
    if device not in {"auto", "cpu", "cuda"}:
        raise ValueError("请选择自动、CPU 或 CUDA")
    python = str(payload.get("pythonPath", previous["pythonPath"]) or "").strip()
    if python:
        python = str(python_executable(python))
    path = locations(root)["settings"]
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with _SETUP_LOCK:
        temporary.write_text(json.dumps({"pythonPath": python, "device": device}), encoding="utf-8")
        temporary.replace(path)
        _probe.cache_clear()


def python_executable(raw):
    path = Path(reject_control_chars(raw, field="Python 解释器")).expanduser().resolve()
    name = path.stem.lower()
    if not name.startswith("python") or any(c not in "python0123456789." for c in name):
        raise ValueError("请选择 Python 解释器")
    if not path.is_file():
        raise ValueError("Python 解释器不存在")
    return path


@lru_cache(maxsize=24)
def _probe(python, packages, executable_mtime):
    script = (
        "import sys,importlib.util,json;from pathlib import Path;"
        "sys.path.insert(0,str(Path(sys.argv[1])/f'python-{sys.version_info.major}.{sys.version_info.minor}'));"
        f"modules={list(MODULES)!r};"
        "print(json.dumps({'version':list(sys.version_info[:3]),"
        "'missing':[m for m in modules if importlib.util.find_spec(m) is None]}))"
    )
    try:
        result = subprocess.run(
            [python, "-c", script, packages], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            return {"version": [], "missing": list(MODULES), "error": result.stderr[-1000:]}
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        return {"version": [], "missing": list(MODULES), "error": str(error)}


def runtime_status(root, config_store=None):
    config = settings(root)
    candidates = []
    if config["pythonPath"]:
        candidates.append(config["pythonPath"])
    else:
        if not getattr(sys, "frozen", False):
            candidates.append(sys.executable)
        api = getattr(getattr(config_store, "config", None), "api_config", None)
        work = str(getattr(api, "t2i_work_path", "") or "")
        if work:
            candidates.append(str(Path(work) / "python_embeded/python.exe"))
        candidates.extend(str(Path(root) / x) for x in ("runtime/python.exe", ".venv/Scripts/python.exe", ".venv/bin/python"))
        candidates.extend(filter(None, (shutil.which("python3.12"), shutil.which("python3.13"))))
    options = []
    for raw in dict.fromkeys(candidates):
        try:
            path = python_executable(raw)
        except ValueError:
            continue
        probe = _probe(str(path), str(locations(root)["packages"]), path.stat().st_mtime_ns)
        version = probe.get("version", [])
        compatible = tuple(version[:2]) >= (3, 12)
        options.append({**probe, "pythonPath": str(path), "compatible": compatible})
    compatible = [x for x in options if x["compatible"]]
    chosen = min(compatible, key=lambda x: len(x["missing"])) if compatible else None
    return {
        "pythonPath": chosen["pythonPath"] if chosen else config["pythonPath"],
        "version": chosen["version"] if chosen else [],
        "missing": chosen["missing"] if chosen else list(MODULES),
        "runtimeReady": bool(chosen and not chosen["missing"]),
        "compatible": bool(chosen), "device": config["device"],
    }


@lru_cache(maxsize=8)
def _verified(path, mtime, size, expected):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected


def verify_weight(path, model):
    path = Path(path)
    try:
        stat = path.stat()
        return stat.st_size == model["size"] and _verified(str(path), stat.st_mtime_ns, stat.st_size, model["sha256"])
    except OSError:
        return False


def status(root, config_store=None):
    model_dir = locations(root)["models"]
    models = [{"id": key, "size": model["size"], "ready": verify_weight(model_dir / f"{key}.safetensors", model)} for key, model in MODEL_FILES.items()]
    return {**runtime_status(root, config_store), "models": models, "modelsReady": all(x["ready"] for x in models), "modelDirectory": str(model_dir)}


def import_models(root, paths):
    if not isinstance(paths, list) or len(paths) != 2:
        raise ValueError("请选择两份模型权重文件")
    directory = locations(root)["models"]
    directory.mkdir(parents=True, exist_ok=True)
    with _SETUP_LOCK:
        identified = {}
        for raw in paths:
            path = Path(reject_control_chars(raw, field="模型文件")).resolve()
            found = next((name for name, model in MODEL_FILES.items() if verify_weight(path, model)), None)
            if not found or found in identified:
                raise ValueError("模型文件不匹配，请下载 YOLOv3 与 HRNetV2 的官方权重")
            identified[found] = path
        for name, path in identified.items():
            target = directory / f"{name}.safetensors"
            if path != target:
                shutil.copyfile(path, target.with_suffix(".tmp"))
                target.with_suffix(".tmp").replace(target)


def download_models(root, progress):
    from huggingface_hub import hf_hub_download

    directory = locations(root)["models"]
    directory.mkdir(parents=True, exist_ok=True)
    with _SETUP_LOCK:
        for index, (name, spec) in enumerate(MODEL_FILES.items()):
            target = directory / f"{name}.safetensors"
            if verify_weight(target, spec):
                continue
            progress(f"正在下载 {name}（{spec['size'] / 1_000_000:.1f} MB）", index / 2)
            downloaded = Path(hf_hub_download(spec["repo"], "model.safetensors", revision=spec["revision"]))
            if not verify_weight(downloaded, spec):
                raise ValueError("口型模型校验失败，请重新下载或导入官方文件")
            temporary = target.with_suffix(".tmp")
            shutil.copyfile(downloaded, temporary)
            temporary.replace(target)
        progress("口型模型已下载并通过校验", 1)


def install_runtime(root, config_store, progress):
    from core.runtime_env.pip_runner import apply_pip_index_and_extra_args, run_pip_install

    current = runtime_status(root, config_store)
    if not current["compatible"]:
        raise ValueError("请先选择 Python 3.12 以上环境；可选择 H3 的 python_embeded/python.exe")
    missing = current["missing"]
    if not missing:
        return
    packages = package_directory(root, current["version"])
    packages.mkdir(parents=True, exist_ok=True)
    specs = [MODULES[module] for module in missing]
    command = [current["pythonPath"], "-m", "pip", "install", "--upgrade", "--target", str(packages), *specs]
    # Reuse existing Torch/CUDA rather than replacing the H3 installation.
    if "torch" not in missing and "torchvision" not in missing:
        command.append("--no-deps")
    code, detail = run_pip_install(
        apply_pip_index_and_extra_args(command), cwd=Path(root), timeout_sec=1800,
        detail_max=3000, on_output_line=lambda line: progress(line, 0.3),
    )
    _probe.cache_clear()
    if code != "pip_ok":
        raise RuntimeError(detail or "口型运行依赖安装失败")
    if not runtime_status(root, config_store)["runtimeReady"]:
        raise RuntimeError("依赖安装后仍不完整，请检查识别环境")


def worker_command(root, config_store, request_path):
    current = status(root, config_store)
    if not current["runtimeReady"] or not current["modelsReady"]:
        raise ValueError("请先在口型同步页准备识别环境和两份模型")
    worker = Path(__file__).resolve().parents[3] / "core/sprite/mouth/worker.py"
    return [current["pythonPath"], str(worker), str(request_path), str(package_directory(root, current["version"]))]


def run_mouth_setup(state, task_id, payload, action):
    root = state.project_root_dir

    def progress(message, value):
        _update_task(state, task_id, phase="mouth-setup", progress=value, message=message)

    if action == "download":
        download_models(root, progress)
    elif action == "install":
        install_runtime(root, state.config_manager, progress)
    return status(root, state.config_manager)


def configure_mouth_setup(state, payload):
    configure(state.project_root_dir, payload)
    return status(state.project_root_dir, state.config_manager)


def import_mouth_models(
    state, payload, *, file_access_roots: Iterable[Path] = ()
):
    paths = payload.get("paths")
    if not isinstance(paths, list) or len(paths) != 2:
        raise ValueError("请选择两份模型文件")
    roots = _resolve_file_access_roots(state, file_access_roots)
    checked = [
        str(safe_existing_file_path(str(path), roots=roots, field="model"))
        for path in paths
    ]
    import_models(state.project_root_dir, checked)
    return status(state.project_root_dir, state.config_manager)
