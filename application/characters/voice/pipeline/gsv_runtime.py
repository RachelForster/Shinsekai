"""GPT-SoVITS local bundle validation, ASR model cache discovery, and cancellable subprocess runner."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import subprocess
import threading
from typing import Any

from ai.tts.tts_adapter import resolve_pretrained_base_models
from application.runtime.tasks import (
    TaskCancelled,
    _append_task_log,
    _is_task_cancel_requested,
)


MODEL_VERSION = "v2ProPlus"
ASR_MODEL_SIZE = "large-v3"
FASTER_WHISPER_REPO = "Systran/faster-whisper-large-v3"


@dataclass(frozen=True, slots=True)
class GsvRuntimeProfile:
    gpu: str = "0"
    batch_size: int = 1
    use_half: bool = False

    @property
    def asr_precision(self) -> str:
        return "int8" if self.batch_size <= 4 else "float16" if self.use_half else "float32"


class SubprocessFailed(RuntimeError):
    def __init__(self, label: str, return_code: int, tail: str = "") -> None:
        self.label = label
        self.return_code = return_code
        suffix = f"：{tail}" if tail else ""
        super().__init__(f"{label}失败（退出码 {return_code}）{suffix}")


def detect_runtime_profile() -> GsvRuntimeProfile:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            check=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=creationflags,
        )
        memory_mib = int(completed.stdout.splitlines()[0].strip())
        memory_gib = memory_mib / 1024.0 + 0.4
        return GsvRuntimeProfile(batch_size=max(1, int(memory_gib // 2)), use_half=True)
    except (OSError, ValueError, subprocess.SubprocessError, IndexError):
        return GsvRuntimeProfile()


def resolve_gpt_sovits_settings(state: Any, project_root: Path) -> tuple[str, Path, str]:
    config_manager = state.config_manager
    get_cfg = getattr(config_manager, "get_gpt_sovits_config", None)
    if callable(get_cfg):
        gsv_url, raw_work_path, provider = get_cfg()
    else:
        api_cfg = config_manager.config.api_config
        gsv_url = str(getattr(api_cfg, "gpt_sovits_url", "") or "http://127.0.0.1:9880/")
        raw_work_path = str(getattr(api_cfg, "gpt_sovits_api_path", "") or "")
        provider = str(getattr(api_cfg, "tts_provider", "") or "gpt-sovits")

    cleaned_path = str(raw_work_path or "").strip().strip('"')
    if not cleaned_path:
        raise ValueError(
            "尚未配置本机 GPT-SoVITS 目录（gpt_sovits_api_path），请先在语音设置中指向整合包根目录。"
        )
    expanded = Path(os.path.expandvars(cleaned_path)).expanduser()
    if not expanded.is_absolute():
        expanded = project_root / expanded
    if expanded.suffix.lower() == ".py":
        expanded = expanded.parent
    root = expanded.resolve(strict=False)
    if not root.is_dir():
        raise FileNotFoundError(f"配置的 GPT-SoVITS 目录不存在：{root}")
    return str(gsv_url or "http://127.0.0.1:9880/"), root, str(provider or "gpt-sovits")


def _resolve_gsv_python(gsv_root: Path) -> Path:
    candidates = [
        gsv_root / "runtime" / ("python.exe" if os.name == "nt" else "python"),
        gsv_root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"未找到 GPT-SoVITS 内置 Python 运行时：{candidates[0]}")


def validate_gsv_bundle(gsv_root: Path, *, train: bool) -> tuple[Path, str, str]:
    gsv_python = _resolve_gsv_python(gsv_root)
    base_required = [
        gsv_root / "tools" / "slice_audio.py",
        gsv_root / "tools" / "asr" / "fasterwhisper_asr.py",
    ]
    if train:
        base_required.extend(
            [
                gsv_root / "GPT_SoVITS" / "configs" / "s2v2ProPlus.json",
                gsv_root / "GPT_SoVITS" / "configs" / "s1longer-v2.yaml",
                gsv_root / "GPT_SoVITS" / "pretrained_models" / "chinese-hubert-base" / "config.json",
                gsv_root / "GPT_SoVITS" / "pretrained_models" / "chinese-roberta-wwm-ext-large" / "config.json",
                gsv_root / "GPT_SoVITS" / "pretrained_models" / "sv" / "pretrained_eres2netv2w24s4ep4.ckpt",
                gsv_root / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Gv2ProPlus.pth",
                gsv_root / "GPT_SoVITS" / "pretrained_models" / "v2Pro" / "s2Dv2ProPlus.pth",
                gsv_root / "GPT_SoVITS" / "pretrained_models" / "s1v3.ckpt",
            ]
        )
    missing = [str(p.relative_to(gsv_root)) for p in base_required if not p.is_file()]
    if missing:
        raise ValueError(f"GPT-SoVITS 整合包缺少必需文件：{'、'.join(missing)}")

    base_gpt, base_sovits = resolve_pretrained_base_models(gsv_root)
    if not train and (not base_gpt or not base_sovits):
        raise ValueError(
            f"GPT-SoVITS 目录中未找到可用的预训练白模（如 s1v3.ckpt + s2Gv2ProPlus.pth）：{gsv_root}"
        )
    return gsv_python, base_gpt, base_sovits


def _faster_whisper_ready(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    names = {item.name.lower() for item in directory.iterdir() if item.is_file()}
    has_config = "config.json" in names
    has_weights = "model.bin" in names or any(name.endswith(".bin") for name in names)
    has_tokenizer = "tokenizer.json" in names or "vocabulary.json" in names
    return has_config and has_weights and has_tokenizer


def _discover_hf_faster_whisper(
    environment: Mapping[str, str] | None = None,
) -> tuple[Path | None, dict[str, str]]:
    env = environment if environment is not None else os.environ
    roots: list[Path] = []
    for key in ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "HF_HOME"):
        raw = str(env.get(key) or "").strip()
        if raw:
            roots.append(Path(raw).expanduser())
    roots.append(Path.home() / ".cache" / "huggingface")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")

    repo_folder = "models--" + FASTER_WHISPER_REPO.replace("/", "--")
    for root in roots:
        for snapshots in (root / "hub" / repo_folder / "snapshots", root / repo_folder / "snapshots"):
            if not snapshots.is_dir():
                continue
            ready = [snap for snap in snapshots.iterdir() if snap.is_dir() and _faster_whisper_ready(snap)]
            if ready:
                ready.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                hf_home = root if root.name != "hub" else root.parent
                hf_hub = hf_home / "hub"
                return ready[0], {
                    "HF_HOME": str(hf_home),
                    "HF_HUB_CACHE": str(hf_hub),
                    "HUGGINGFACE_HUB_CACHE": str(hf_hub),
                    "TRANSFORMERS_CACHE": str(hf_home),
                    "HF_HUB_OFFLINE": "1",
                    "HF_HUB_DISABLE_TELEMETRY": "1",
                }
    return None, {"HF_HUB_DISABLE_TELEMETRY": "1"}


def resolve_asr_model_arg_and_env(gsv_root: Path) -> tuple[str, dict[str, str]]:
    local_dir = gsv_root / "tools" / "asr" / "models" / f"faster-whisper-{ASR_MODEL_SIZE}"
    if _faster_whisper_ready(local_dir):
        return f"{ASR_MODEL_SIZE}-local", {
            "HF_HUB_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
    _cached_snapshot, extra_env = _discover_hf_faster_whisper()
    return ASR_MODEL_SIZE, extra_env


def validate_asr_list_complete(list_path: Path) -> int:
    if not list_path.is_file():
        raise RuntimeError(f"ASR 未生成标注文件：{list_path}")
    lines = [line for line in list_path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    if not lines or any(line.count("|") < 3 for line in lines):
        raise RuntimeError(f"ASR 标注结果为空或格式无效：{list_path}")
    return len(lines)


class CancellableGsvRunner:
    """Execute GPT-SoVITS / ffmpeg / yt-dlp child processes with live task logging and tree termination."""

    def __init__(
        self,
        *,
        state: Any,
        task_id: str,
        gsv_root: Path,
        gsv_python: Path,
        profile: GsvRuntimeProfile,
    ) -> None:
        self.state = state
        self.task_id = task_id
        self.gsv_root = gsv_root
        self.gsv_python = gsv_python
        self.profile = profile
        self._lock = threading.RLock()
        self._processes: dict[int, subprocess.Popen[str]] = {}

    def check_cancelled(self) -> None:
        if _is_task_cancel_requested(self.state, self.task_id):
            self.terminate_all()
            raise TaskCancelled()

    def log(self, line: str) -> None:
        _append_task_log(self.state, self.task_id, line)

    def python_cmd(self, script: str | Path, *args: str) -> list[str]:
        return [str(self.gsv_python), "-X", "utf8", "-u", "-s", str(script), *args]

    def base_env(self) -> dict[str, str]:
        env = os.environ.copy()
        runtime_dir = str(self.gsv_root / "runtime")
        env["PATH"] = str(self.gsv_root) + os.pathsep + runtime_dir + os.pathsep + env.get("PATH", "")
        temp_dir = self.gsv_root / "TEMP"
        temp_dir.mkdir(parents=True, exist_ok=True)
        env.update(
            {
                "TEMP": str(temp_dir),
                "TMP": str(temp_dir),
                "PYTHONUTF8": "1",
                "PYTHONUNBUFFERED": "1",
                "is_half": str(self.profile.use_half),
                "version": MODEL_VERSION,
            }
        )
        return env

    def terminate_all(self) -> None:
        with self._lock:
            active = list(self._processes.values())
        for proc in active:
            self._kill_tree(proc)

    @staticmethod
    def _kill_tree(proc: subprocess.Popen[str]) -> None:
        if proc.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=15,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                proc.terminate()
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError:
                pass

    def run(
        self,
        label: str,
        command: Sequence[str],
        *,
        cwd: Path | None = None,
        extra_env: Mapping[str, str] | None = None,
    ) -> None:
        self.check_cancelled()
        env = self.base_env()
        if extra_env:
            env.update({k: str(v) for k, v in extra_env.items()})
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            [str(part) for part in command],
            cwd=str(cwd or self.gsv_root),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=creationflags,
        )
        with self._lock:
            self._processes[proc.pid] = proc
        out_q: queue.Queue[str | None] = queue.Queue()
        recent_lines: list[str] = []

        def _reader() -> None:
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                out_q.put(raw_line.rstrip())
            out_q.put(None)

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        eof = False
        try:
            while proc.poll() is None or not eof:
                if _is_task_cancel_requested(self.state, self.task_id):
                    self._kill_tree(proc)
                    raise TaskCancelled()
                try:
                    line = out_q.get(timeout=0.25)
                except queue.Empty:
                    continue
                if line is None:
                    eof = True
                elif line:
                    recent_lines.append(line)
                    if len(recent_lines) > 8:
                        recent_lines.pop(0)
                    self.log(line)
            rc = proc.wait()
            if rc != 0:
                tail = " | ".join(recent_lines[-3:])
                raise SubprocessFailed(label, rc, tail)
        finally:
            with self._lock:
                self._processes.pop(proc.pid, None)
            if proc.stdout is not None:
                proc.stdout.close()
