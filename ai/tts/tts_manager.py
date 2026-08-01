import requests
import os
import threading
import queue
import subprocess
import time
import uuid
from ai.tts.tts_adapter import (
    TTSAdapter,
    GPTSoVitsAdapter,
    KaggleGPTSoVitsAdapter,
    IndexTTSAdapter,
    CosyVoiceAdapter,
    GenieTTSAdapter,
    _popen_local_python_service,
)
from pathlib import Path
from sdk.path_contract import (
    managed_project_storage,
    project_root as runtime_project_root,
    require_directory_without_links,
    require_regular_file_without_links,
    resolve_project_path,
    resolve_runtime_asset_read_path,
)
from sdk.file_transactions import (
    capture_directory_identity,
    private_sibling_path,
    remove_file_without_links,
    replace_file_transactionally,
)

class TTSAdapterFactory:
    """
    Factory for creating different TTSAdapter instances.
    """
    _adapters = {
        'gpt-sovits': GPTSoVitsAdapter,
        'kaggle-gpt-sovits': KaggleGPTSoVitsAdapter,
        'genie-tts': GenieTTSAdapter,
        'index-tts': IndexTTSAdapter,
        'cosyvoice': CosyVoiceAdapter,
    }

    @staticmethod
    def create_adapter(adapter_name: str, *, wait_until_ready: bool = False, **kwargs) -> TTSAdapter:
        """
        Creates and returns a TTSAdapter instance based on the given name.

        Args:
            adapter_name (str): The name of the adapter to create (e.g., 'elevenlabs').
            **kwargs: Configuration arguments for the adapter's constructor (e.g., api_key, work_path).

        Returns:
            TTSAdapter: An instance of a concrete TTSAdapter.

        Raises:
            ValueError: If the adapter name is not supported.
        """
        adapter_class = TTSAdapterFactory._adapters.get(adapter_name.lower())

        if not adapter_class:
            raise ValueError(f"Unsupported TTS adapter: '{adapter_name}'. Supported adapters are: {list(TTSAdapterFactory._adapters.keys())}")

        try:
            # Instantiate the correct adapter class with the provided kwargs
            adapter = adapter_class(**kwargs)
            if wait_until_ready:
                try:
                    adapter.wait_until_ready()
                except BaseException:
                    stop_server = getattr(adapter, "stop_server", None)
                    if callable(stop_server):
                        stop_server()
                    raise
            return adapter
        except TypeError as e:
            print(f"Error creating adapter '{adapter_name}'. Check the required arguments.")
            raise e


#  TTS管理器
class TTSManager:
    def __init__(
        self,
        character_ui_url="http://localhost:7888/alive",
        tts_server_url="http://127.0.0.1:9880/",
        *,
        project_root: str | Path | None = None,
    ):
        if project_root is None:
            root = runtime_project_root()
        else:
            root = resolve_project_path(".", root=project_root)
        self.project_root = root
        self.audio_cache_dir = managed_project_storage(
            "data/cache/audio",
            root=root,
        )
        self.character_ui_url = character_ui_url
        self.cache_num = 100
        self.index = 0

        self.audio_cache_dir.mkdir(exist_ok=True, parents=True)
        self.audio_cache_dir = require_directory_without_links(
            self.audio_cache_dir,
            field="TTS audio cache directory",
        )
        # Use the adapter for TTS operations
        self.tts_adapter = None

        # Work queue for processing speak/sing requests
        self.task_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._process_queue, daemon=True)
        self.worker_thread.start()

        self.voice_language = "ja"  # Default voice language is Japanese

    def set_tts_adapter(self, adapter: TTSAdapter):
        """Allows switching the TTS adapter at runtime."""
        self.tts_adapter = adapter

    def _is_valid_audio_file(self, path: str | Path | None) -> bool:
        if not path:
            return False
        try:
            p = resolve_runtime_asset_read_path(path, root=self.project_root)
            return p.is_file() and p.stat().st_size > 0
        except (OSError, PermissionError, RuntimeError, ValueError):
            return False

    def generate_tts(self, text, text_processor=None, ref_audio_path=None,
                     prompt_text=None, prompt_lang=None, character_name=None,
                     speed_factor=None):
        """Generates TTS audio using the currently set adapter."""
        print("Generating speech")

        # Pre-process the text using the provided processor
        if text_processor:
            text = text_processor.remove_parentheses(text)
            text = text_processor.html_to_plain_qt(text)
            language = text_processor.decide_language(text)
            text = text_processor.replace_names(text)
            if language != self.voice_language:
                text = text_processor.libre_translate(text, source=language, target=self.voice_language)
            if self.voice_language == 'ja' and (character_name == "狛枝凪斗" or character_name == "仆役" or character_name == "小狛枝"):
                text = text_processor.replace_watashi(text)

        if not ref_audio_path:
            print("No reference audio provided")
            return ''
        try:
            ref_audio_path = resolve_runtime_asset_read_path(
                str(ref_audio_path),
                root=self.project_root,
            ).as_posix()
        except (OSError, PermissionError, RuntimeError, ValueError) as exc:
            print(f"Reference audio path is invalid: {exc}")
            return ""

        # Bind the complete adapter call and final publication to the same
        # cache directory. A path-only adapter may run for seconds; accepting a
        # same-named replacement directory afterward would publish into a
        # different project than the one selected at call entry.
        audio_cache_dir, audio_cache_identity = capture_directory_identity(
            self.audio_cache_dir,
            field="TTS audio cache directory",
        )

        # 最终文件路径
        final_path = audio_cache_dir / f"{self.index % self.cache_num}.wav"
        self.index += 1
        try:
            final_identity = final_path.lstat()
        except FileNotFoundError:
            final_identity = None

        attempts = 2
        for attempt in range(1, attempts + 1):
            tmp_path = private_sibling_path(
                final_path,
                f".{uuid.uuid4().hex}.part",
                field="TTS staging audio",
            )
            tmp_identity = None
            try:
                result = self.tts_adapter.generate_speech(
                    text=text,
                    file_path=str(tmp_path),
                    ref_audio_path=ref_audio_path,
                    prompt_text=prompt_text,
                    prompt_lang=prompt_lang,
                    text_lang=self.voice_language,
                    character_name=character_name,
                    speed_factor=speed_factor,
                )
                if os.path.lexists(tmp_path):
                    tmp_identity = tmp_path.lstat()
                if result and tmp_identity is not None and self._is_valid_audio_file(tmp_path):
                    replace_file_transactionally(
                        tmp_path,
                        final_path,
                        expected_staging_identity=tmp_identity,
                        expected_destination_identity=final_identity,
                        expected_parent_identity=audio_cache_identity,
                    )
                    return str(final_path)
                print(f"TTS generation returned no usable audio (attempt {attempt}/{attempts}).")
            finally:
                if tmp_identity is None and os.path.lexists(tmp_path):
                    tmp_identity = tmp_path.lstat()
                if tmp_identity is not None:
                    remove_file_without_links(
                        tmp_path,
                        missing_ok=True,
                        expected_identity=tmp_identity,
                    )
            if attempt < attempts:
                time.sleep(0.35 * attempt)
        return ''

    def set_language(self, language):
        """Sets the voice language."""
        self.voice_language = language

    def switch_model(self, model_info):
        """Switches the TTS model via the adapter."""
        if model_info is None:
            print("No model info provided, cannot switch model.")
            return
        self.tts_adapter.switch_model(model_info)

    # ---------------- Used in the THA mode ------------------------------
    def _process_queue(self):
        """Worker thread to process tasks in the queue sequentially."""
        while True:
            task = self.task_queue.get()
            if task is None:  # Termination signal
                break
            try:
                if task['type'] == 'speak':
                    self._send_audio_to_character(task['file_path'])
                elif task['type'] == 'sing':
                    self._send_song_to_character(task['voice_path'], task['music_path'])
            except Exception as e:
                print(f"TTS task failed: {e}")
            finally:
                self.task_queue.task_done()
    def queue_speech(self, text, language_processor=None):
        """Adds text to the TTS queue."""
        file_path = self.generate_tts(text, language_processor)
        if file_path:
            self.task_queue.put({
                'type': 'speak',
                'file_path': file_path
            })

    def queue_song(self, voice_path, music_path):
        """Adds a song to the queue."""
        self.task_queue.put({
            'type': 'sing',
            'voice_path': voice_path,
            'music_path': music_path
        })

    def _send_audio_to_character(self, file_path):
        """Sends audio file to the character UI."""
        params = {
            "type": "speak",
            "speech_path": file_path,
        }
        try:
            response = requests.post(self.character_ui_url, json=params)
            if response.status_code == 200:
                print(f"Audio sent successfully: {file_path}")
            else:
                print(f"Failed to send audio: {response.text}")
        except Exception as e:
            print(f"Failed to send audio to character UI: {e}")

    def _send_song_to_character(self, voice_path, music_path):
        """Sends a song to the character UI."""
        params = {
            "type": "sing",
            "voice_path": voice_path,
            "music_path": music_path,
        }
        try:
            response = requests.post(self.character_ui_url, json=params)
            if response.status_code == 200:
                print(f"Song sent successfully: {voice_path}, {music_path}")
            else:
                print(f"Failed to send song: {response.text}")
        except Exception as e:
            print(f"Failed to send song to character UI: {e}")

    # Kept for the legacy batch voice-line tool. New runtime code starts the
    # service through the adapter.
    def load_tts_model(
        self,
        gpt_sovits_work_path: str | Path | None = None,
    ):
        """Loads the TTS model by starting the server process."""
        raw = "" if gpt_sovits_work_path is None else str(gpt_sovits_work_path)
        if not raw:
            raise ValueError("GPT-SoVITS work path is required")
        os_path = resolve_runtime_asset_read_path(
            raw,
            root=self.project_root,
            resource_prefixes=(),
        )
        os_path = require_directory_without_links(
            os_path,
            field="GPT-SoVITS work directory",
        )
        from ai.tts.tts_adapter import _bundled_python_path

        embedded_python_path = _bundled_python_path(os_path)
        if embedded_python_path is None:
            raise FileNotFoundError(f"Bundled runtime Python not found under: {os_path}")
        path = os_path / "api_v2.py"
        try:
            path = require_regular_file_without_links(
                path,
                field="GPT-SoVITS startup script",
            )
        except FileNotFoundError:
            raise FileNotFoundError(
                f"GPT-SoVITS api_v2.py not found: {path}"
            ) from None
        _popen_local_python_service(
            service_name="GPT-SoVITS",
            work_root=os_path,
            python_path=embedded_python_path,
            script_path=path,
            popen_factory=subprocess.Popen,
        )

    def shutdown(self):
        """Shuts down the queue, worker thread, and TTS server process."""
        self.task_queue.put(None)
        self.worker_thread.join()
        if hasattr(self.tts_adapter, "stop_server"):
            self.tts_adapter.stop_server()
