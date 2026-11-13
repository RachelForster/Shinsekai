"""Subprocess manager for one-click launch of `tools/perception_local_server.py`."""

from __future__ import annotations

import atexit
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from typing import Any
from urllib.parse import urlparse

from ai.perception.decision_client import PerceptionDecisionClient
from core.perception.models import GGUF_MODEL_ID, PerceptionConfig

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}


def _python_in_env_dir(env_dir: Path) -> Path | None:
    if os.name == "nt":
        candidate = env_dir / "python.exe"
        if candidate.is_file():
            return candidate
        scripts_candidate = env_dir / "Scripts" / "python.exe"
        if scripts_candidate.is_file():
            return scripts_candidate
    else:
        for rel in ("bin/python3", "bin/python"):
            candidate = env_dir / rel
            if candidate.is_file():
                return candidate
    return None


def _site_packages_dirs(python_exe: Path) -> list[Path]:
    env_root = python_exe.parent
    if env_root.name.lower() in {"scripts", "bin"}:
        env_root = env_root.parent

    found: list[Path] = []
    win_sp = env_root / "Lib" / "site-packages"
    if win_sp.is_dir():
        found.append(win_sp)
    lib_dir = env_root / "lib"
    if lib_dir.is_dir():
        for child in lib_dir.glob("python*"):
            posix_sp = child / "site-packages"
            if posix_sp.is_dir():
                found.append(posix_sp)
    return found


def _score_python_candidate(python_exe: Path) -> int:
    """Return >0 only when both `torch` and `transformers` exist in site-packages."""
    if not python_exe.is_file():
        return 0
    sp_dirs = _site_packages_dirs(python_exe)
    if not sp_dirs:
        return 0

    has_torch = False
    has_transformers = False
    has_cuda = False
    has_pil = False

    for sp in sp_dirs:
        torch_dir = sp / "torch"
        if torch_dir.is_dir():
            has_torch = True
            torch_lib = torch_dir / "lib"
            if (
                (torch_lib / "torch_cuda.dll").is_file()
                or (torch_lib / "libc10_cuda.so").is_file()
                or any(torch_lib.glob("*cuda*"))
            ):
                has_cuda = True
        if (sp / "transformers").is_dir():
            has_transformers = True
        if (sp / "PIL").is_dir():
            has_pil = True

    if not (has_torch and has_transformers):
        return 0

    score = 50
    if has_cuda:
        score += 100
    if has_pil:
        score += 10
    # Slight preference for dedicated ML envs like `eaiv`
    lower_str = str(python_exe).lower()
    if "eaiv" in lower_str or "qwen" in lower_str or "vlm" in lower_str:
        score += 5
    return score


def _iter_candidate_env_dirs() -> list[Path]:
    dirs: list[Path] = []
    seen: set[str] = set()

    def _add(p: Path) -> None:
        try:
            norm = os.path.normcase(str(p.expanduser()))
        except Exception:
            return
        if norm in seen:
            return
        seen.add(norm)
        dirs.append(Path(p).expanduser())

    if conda_prefix := os.environ.get("CONDA_PREFIX", "").strip():
        _add(Path(conda_prefix))

    home = Path.home()
    envs_txt = home / ".conda" / "environments.txt"
    if envs_txt.is_file():
        try:
            for line in envs_txt.read_text(encoding="utf-8", errors="ignore").splitlines():
                clean = line.strip()
                if clean:
                    _add(Path(clean))
        except OSError:
            pass

    env_roots = [
        home / ".conda" / "envs",
        home / "miniconda3" / "envs",
        home / "anaconda3" / "envs",
        home / "miniforge3" / "envs",
        home / "AppData" / "Local" / "miniconda3" / "envs",
        home / "AppData" / "Local" / "anaconda3" / "envs",
    ]
    if os.name == "nt":
        env_roots.extend(
            [
                Path("C:/ProgramData/miniconda3/envs"),
                Path("C:/ProgramData/anaconda3/envs"),
            ]
        )

    for root in env_roots:
        if root.is_dir():
            try:
                for child in sorted(root.iterdir()):
                    if child.is_dir():
                        _add(child)
            except OSError:
                continue

    return dirs


def discover_perception_python(explicit_path: str = "") -> str:
    """Resolve explicit Python path or auto-detect the best local Torch+Transformers Python."""
    raw = str(explicit_path or os.environ.get("SHINSEKAI_PERCEPTION_PYTHON") or "").strip().strip('"')
    if raw:
        p = Path(raw).expanduser()
        if p.is_dir():
            exe = _python_in_env_dir(p)
            if exe is not None:
                return str(exe)
            raise ValueError(f"指定的环境目录中未找到 Python 可执行文件：{p}")
        if p.is_file():
            return str(p)
        raise ValueError(f"指定的 Python 路径不存在：{p}")

    best_path = ""
    best_score = 0

    for env_dir in _iter_candidate_env_dirs():
        exe = _python_in_env_dir(env_dir)
        if exe is None:
            continue
        score = _score_python_candidate(exe)
        if score > best_score:
            best_score = score
            best_path = str(exe)

    # Check current interpreter as fallback if it has torch + transformers
    current_exe = Path(sys.executable)
    cur_score = _score_python_candidate(current_exe)
    if cur_score > best_score:
        best_score = cur_score
        best_path = str(current_exe)

    return best_path


def resolve_local_server_script() -> Path:
    """Locate `tools/perception_local_server.py` across dev and packaged layouts."""
    candidates: list[Path] = []
    for env_key in ("SHINSEKAI_SOURCE_ROOT", "SHINSEKAI_APP_ROOT", "SHINSEKAI_PROJECT_ROOT"):
        val = os.environ.get(env_key, "").strip()
        if val:
            candidates.append(Path(val) / "tools" / "perception_local_server.py")
    candidates.append(Path(__file__).resolve().parents[2] / "tools" / "perception_local_server.py")
    candidates.append(Path.cwd() / "tools" / "perception_local_server.py")

    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("未找到本地感知服务脚本 tools/perception_local_server.py")


def parse_local_server_endpoint(base_url: str) -> tuple[str, int]:
    """Validate that `base_url` targets localhost and return `(bind_host, port)`."""
    clean = str(base_url or "http://127.0.0.1:8091/v1").strip() or "http://127.0.0.1:8091/v1"
    parsed = urlparse(clean)
    if parsed.scheme.lower() != "http":
        raise ValueError("一键启动本地推理服务仅支持本机 http:// 地址。")
    hostname = (parsed.hostname or "").strip().lower()
    if hostname not in _LOCAL_HOSTS:
        raise ValueError(
            f"当前感知地址（{hostname or clean}）不是本机地址，仅 127.0.0.1 / localhost 支持一键启动。"
        )
    port = int(parsed.port or 8091)
    if port < 1 or port > 65535:
        raise ValueError(f"端口号无效：{port}")
    bind_host = "0.0.0.0" if hostname == "0.0.0.0" else "127.0.0.1"
    return bind_host, port


def _gguf_arguments(root: Path) -> list[str]:
    directory = root / "data" / "cache" / "perception-gguf"
    executable = "llama-server.exe" if os.name == "nt" else "llama-server"
    files = (
        directory / "llama.cpp" / executable,
        directory / "Qwen3VL-2B-Instruct-Q4_K_M.gguf",
        directory / "mmproj-Qwen3VL-2B-Instruct-F16.gguf",
    )
    missing = [file.name for file in files if not file.is_file()]
    if missing:
        raise ValueError(f"Q4 感知服务缺少 {', '.join(missing)}。资源目录：{directory}")
    return ["--gguf", *(str(file) for file in files)]


class PerceptionLocalServerManager:
    """Manage lifecycle, log capture, and readiness probing of `perception_local_server.py`."""

    def __init__(
        self,
        *,
        probe_fn: Callable[[PerceptionConfig], dict[str, Any]] | None = None,
        popen_fn: Callable[..., subprocess.Popen[str]] = subprocess.Popen,
    ) -> None:
        self._lock = threading.RLock()
        self._proc: subprocess.Popen[str] | None = None
        self._state: str = "stopped"
        self._python_path: str = ""
        self._base_url: str = "http://127.0.0.1:8091/v1"
        self._port: int = 8091
        self._model: str = "Qwen/Qwen3-VL-2B-Instruct"
        self._error: str = ""
        self._logs: deque[str] = deque(maxlen=60)
        self._generation: int = 0
        self._probe_fn = probe_fn or (
            lambda cfg: PerceptionDecisionClient().probe_health(cfg, timeout=1.2)
        )
        self._popen_fn = popen_fn

    def _refresh_locked(self) -> None:
        proc = self._proc
        if proc is None:
            return
        rc = proc.poll()
        if rc is None:
            return
        self._proc = None
        if self._state in {"starting", "running"}:
            self._state = "failed" if rc != 0 else "stopped"
            if rc != 0 and not self._error:
                tail = list(self._logs)[-3:]
                self._error = " | ".join(tail) if tail else f"进程异常退出（exit code {rc}）"

    def status(self, *, explicit_python_path: str = "") -> dict[str, Any]:
        detected = ""
        try:
            detected = discover_perception_python(explicit_python_path)
        except ValueError:
            detected = ""
        with self._lock:
            self._refresh_locked()
            proc = self._proc
            state = self._state
            return {
                "state": state,
                "running": state in {"running", "external_running"},
                "starting": state == "starting",
                "managed": proc is not None and proc.poll() is None,
                "pid": proc.pid if (proc is not None and proc.poll() is None) else None,
                "pythonPath": self._python_path or detected,
                "detectedPythonPath": detected,
                "baseUrl": self._base_url,
                "model": self._model,
                "error": self._error,
                "logs": list(self._logs)[-20:],
            }

    def start(
        self,
        *,
        base_url: str = "http://127.0.0.1:8091/v1",
        model: str = "Qwen/Qwen3-VL-2B-Instruct",
        python_path: str = "",
        device: str = "cuda:0",
    ) -> dict[str, Any]:
        clean_base_url = str(base_url or "http://127.0.0.1:8091/v1").strip() or "http://127.0.0.1:8091/v1"
        clean_model = str(model or "Qwen/Qwen3-VL-2B-Instruct").strip() or "Qwen/Qwen3-VL-2B-Instruct"
        bind_host, port = parse_local_server_endpoint(clean_base_url)
        script_path = resolve_local_server_script() if clean_model == GGUF_MODEL_ID else None
        gguf_arguments = _gguf_arguments(script_path.parent.parent) if script_path is not None else []

        with self._lock:
            self._refresh_locked()
            if (
                self._proc is not None
                and self._proc.poll() is None
                and self._port == port
                and self._model == clean_model
            ):
                return self.status(explicit_python_path=python_path)

        # If managed process is running with old port/model, stop it first.
        if self._proc is not None:
            self.stop()

        # Check if an external server is already listening on this port.
        probe_cfg = PerceptionConfig(base_url=clean_base_url, model=clean_model)
        existing = self._probe_fn(probe_cfg)
        if existing.get("ok"):
            if existing.get("modelPresent") is False:
                active_models = "、".join(existing.get("models") or ())
                raise ValueError(f"端口 {port} 上正在运行 {active_models or '其他感知模型'}。请先停止该感知服务。")
            with self._lock:
                self._state = "external_running"
                self._base_url = clean_base_url
                self._port = port
                self._model = clean_model
                self._error = ""
            return self.status(explicit_python_path=python_path)

        resolved_python = discover_perception_python(python_path)
        if not resolved_python:
            raise ValueError(
                "未自动检测到包含 PyTorch 与 Transformers 的本地 Python 环境，请在下方填写 Python 解释器路径（如 Conda 环境下的 python.exe）。"
            )
        script_path = script_path or resolve_local_server_script()

        cmd = [
            resolved_python,
            "-u",
            str(script_path),
            "--host",
            bind_host,
            "--port",
            str(port),
            "--model",
            clean_model,
            "--device",
            str(device or "cuda:0").strip() or "cuda:0",
            "--stop-on-stdin-eof",
            *gguf_arguments,
        ]
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # Shinsekai's mirror_env redirects HF_HOME/HF_HUB_CACHE to ./data/cache/huggingface.
        # If the user already cached the VLM in ~/.cache/huggingface/hub, point directly there.
        user_hf_hub = Path.home() / ".cache" / "huggingface" / "hub"
        repo_dir_name = "models--" + clean_model.replace("/", "--")
        if (user_hf_hub / repo_dir_name / "snapshots").is_dir():
            for key in ("HF_HOME", "TRANSFORMERS_CACHE"):
                env.pop(key, None)
            env["HF_HUB_CACHE"] = str(user_hf_hub)
            env["HUGGINGFACE_HUB_CACHE"] = str(user_hf_hub)

        popen_kwargs: dict[str, Any] = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
            "env": env,
            "cwd": str(script_path.parent.parent),
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = self._popen_fn(cmd, **popen_kwargs)

        with self._lock:
            self._generation += 1
            gen = self._generation
            self._proc = proc
            self._state = "starting"
            self._python_path = resolved_python
            self._base_url = clean_base_url
            self._port = port
            self._model = clean_model
            self._error = ""
            self._logs.clear()
            self._logs.append(
                f"[launcher] Starting {clean_model} on {bind_host}:{port} via {resolved_python}"
            )

        threading.Thread(
            target=self._read_stdout_loop,
            args=(proc, gen),
            name="perception-server-log-reader",
            daemon=True,
        ).start()
        threading.Thread(
            target=self._poll_readiness_loop,
            args=(proc, gen, probe_cfg),
            name="perception-server-readiness",
            daemon=True,
        ).start()

        return self.status(explicit_python_path=python_path)

    def _read_stdout_loop(self, proc: subprocess.Popen[str], gen: int) -> None:
        stream = proc.stdout
        if stream is None:
            return
        try:
            for raw_line in stream:
                line = raw_line.rstrip("\r\n")
                if not line:
                    continue
                with self._lock:
                    if self._generation == gen:
                        self._logs.append(line)
        except Exception:
            pass
        finally:
            with self._lock:
                if self._generation == gen:
                    self._refresh_locked()

    def _poll_readiness_loop(
        self,
        proc: subprocess.Popen[str],
        gen: int,
        probe_cfg: PerceptionConfig,
    ) -> None:
        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            time.sleep(0.5)
            with self._lock:
                if self._generation != gen or self._proc is not proc:
                    return
                if proc.poll() is not None:
                    self._refresh_locked()
                    return
            health = self._probe_fn(probe_cfg)
            if health.get("ok") and health.get("modelPresent") is not False:
                with self._lock:
                    if self._generation == gen and self._proc is proc:
                        self._state = "running"
                        self._error = ""
                return

        with self._lock:
            if self._generation == gen and self._proc is proc and self._state == "starting":
                self._error = "等待本地模型加载超时（120s），请检查日志或模型权重缓存。"

    def stop(self, *, timeout: float = 3.0) -> dict[str, Any]:
        with self._lock:
            self._generation += 1
            proc = self._proc
            gguf = self._model == GGUF_MODEL_ID
            self._proc = None
            self._state = "stopped"
            self._error = ""
        if proc is not None and proc.poll() is None:
            if proc.stdin is not None:
                try:
                    proc.stdin.close()
                    proc.wait(timeout=max(0.2, timeout))
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if proc is not None and proc.poll() is None:
            try:
                if gguf and os.name == "nt":
                    subprocess.run(
                        [str(Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"),
                         "/T", "/F", "/PID", str(proc.pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        timeout=max(0.2, timeout),
                        check=False,
                    )
                proc.terminate()
                proc.wait(timeout=max(0.2, timeout))
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
            except Exception:
                pass
        with self._lock:
            self._logs.append("[launcher] Local perception server stopped.")
        return self.status()


_manager_lock = threading.Lock()
_default_manager: PerceptionLocalServerManager | None = None


def get_perception_server_manager() -> PerceptionLocalServerManager:
    global _default_manager
    with _manager_lock:
        if _default_manager is None:
            _default_manager = PerceptionLocalServerManager()
        return _default_manager


def resolve_perception_config(api_config: Any) -> PerceptionConfig:
    return PerceptionConfig.from_api_config(api_config)


def probe_perception(
    config: PerceptionConfig, options: Mapping[str, Any], *, image: bool = False,
) -> dict[str, Any]:
    config = replace(
        config,
        base_url=str(options.get("baseUrl") or "").strip() or config.base_url,
        api_key=str(options.get("apiKey") or "").strip() or config.api_key,
        model=str(options.get("model") or "").strip() or config.model,
    )
    client = PerceptionDecisionClient()
    return client.probe_image(config) if image else client.probe_health(config)


def switch_running_perception_model(previous: Any, updated: Any) -> None:
    if previous.perception_use_gguf == updated.perception_use_gguf:
        return
    old_endpoint = PerceptionConfig.from_api_config(previous)
    new_endpoint = PerceptionConfig.from_api_config(updated)
    if old_endpoint.base_url != new_endpoint.base_url or old_endpoint.model == new_endpoint.model:
        return
    manager = get_perception_server_manager()
    status = manager.status(explicit_python_path=updated.perception_python_path)
    if status["managed"] and status["baseUrl"] == new_endpoint.base_url and status["model"] != new_endpoint.model:
        manager.start(base_url=new_endpoint.base_url, model=new_endpoint.model, python_path=updated.perception_python_path)


def shutdown_perception_local_server() -> None:
    with _manager_lock:
        mgr = _default_manager
    if mgr is not None:
        mgr.stop(timeout=2.0)


atexit.register(shutdown_perception_local_server)
