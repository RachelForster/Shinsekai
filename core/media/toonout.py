"""A local GPU worker that does not add PyTorch to the desktop core runtime."""

import base64
from io import BytesIO
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Thread

from core.media.toonout_assets import model_directory, verify_assets


class ToonOutUnavailable(RuntimeError):
    pass


class ToonOutSession:
    def __init__(self):
        self.process = None
        self.reader = None
        self.log = None
        directory = model_directory()
        try:
            verify_assets(directory)
            runtime = directory / "runtime.json"
            python = (
                json.loads(runtime.read_text(encoding="utf-8"))["python"]
                if runtime.exists()
                else sys.executable
            )
            if not Path(python).is_file():
                raise FileNotFoundError("ToonOut Python does not exist")
            self.log = (directory / "worker.log").open("a", encoding="utf-8")
            env = {
                key: value
                for key, value in os.environ.items()
                if key
                not in (
                    "PYTHONHOME",
                    "PYTHONPATH",
                    "PYTHONEXECUTABLE",
                    "__PYVENV_LAUNCHER__",
                )
            }
            env["PYTHONUTF8"] = "1"
            self.process = subprocess.Popen(
                [
                    str(python),
                    "-u",
                    str(Path(__file__).with_name("toonout_worker.py")),
                    str(directory),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.log,
                text=True,
                encoding="utf-8",
                env=env,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.responses = Queue()
            self.reader = Thread(target=self._read, daemon=True)
            self.reader.start()
            ready = self._receive(180)
            if not ready.get("ready"):
                raise RuntimeError("ToonOut worker did not initialize")
            self.device = ready["device"]
        except Exception as exc:
            self.close()
            raise ToonOutUnavailable(str(exc)) from exc

    def _read(self):
        try:
            for line in self.process.stdout:
                self.responses.put(json.loads(line))
        except Exception as exc:
            self.responses.put({"error": str(exc)})
        finally:
            self.responses.put({"error": "ToonOut worker exited"})

    def _receive(self, timeout):
        try:
            response = self.responses.get(timeout=timeout)
        except Empty as exc:
            raise RuntimeError(
                "ToonOut 处理超时，请查看 cache/models/toonout/worker.log"
            ) from exc
        if response.get("error"):
            raise RuntimeError(response["error"])
        return response

    def __call__(self, image):
        from PIL import Image

        data = BytesIO()
        image.convert("RGB").save(data, "PNG", compress_level=1)
        self.process.stdin.write(
            json.dumps({"image": base64.b64encode(data.getvalue()).decode("ascii")})
            + "\n"
        )
        self.process.stdin.flush()
        response = self._receive(120)
        with Image.open(BytesIO(base64.b64decode(response["image"]))) as output:
            result = output.convert("RGBA")
        if result.size != image.size:
            raise RuntimeError("ToonOut 改变了画面尺寸")
        return result

    def close(self):
        process = self.process
        if process is not None:
            try:
                if process.poll() is None:
                    process.stdin.write('{"close": true}\n')
                    process.stdin.flush()
                    process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=5)
            finally:
                for stream in (process.stdin, process.stdout):
                    if stream:
                        stream.close()
        if self.reader:
            self.reader.join(timeout=1)
        if self.log:
            self.log.close()
