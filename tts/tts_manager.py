import requests
import threading
import queue
import subprocess
from tts.tts_adapter import TTSAdapter, GPTSoVitsAdapter, IndexTTSAdapter, CosyVoiceAdapter
from pathlib import Path

class TTSAdapterFactory:
    """
    Factory for creating different TTSAdapter instances.
    """
    _adapters = {
        'gpt-sovits': GPTSoVitsAdapter,
        'index-tts': IndexTTSAdapter,
        'cosyvoice': CosyVoiceAdapter,
    }

    @staticmethod
    def create_adapter(adapter_name: str, **kwargs) -> TTSAdapter:
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
            return adapter_class(**kwargs)
        except TypeError as e:
            print(f"Error creating adapter '{adapter_name}'. Check the required arguments.")
            raise e


#  TTS管理器
class TTSManager:
    def __init__(self, character_ui_url="http://localhost:7888/alive", tts_server_url="http://127.0.0.1:9880/"):
        self.audio_cache_dir = Path(".\\cache\\audio")
        self.character_ui_url = character_ui_url
        self.cache_num = 10
        self.index = 0

        self.audio_cache_dir.mkdir(exist_ok=True, parents=True)
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

    def generate_tts(self, text, text_processor=None, ref_audio_path=None, prompt_text=None, prompt_lang=None, character_name=None):
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

        # The adapter handles the specifics of the TTS generation
        file_path = f'cache\\audio\\{self.index % self.cache_num}.wav'
        self.index += 1
        
        return self.tts_adapter.generate_speech(
            text=text,
            file_path=file_path,
            ref_audio_path=ref_audio_path,
            prompt_text=prompt_text,
            prompt_lang=prompt_lang,
            text_lang=self.voice_language
        )

    def set_language(self, language):
        """Sets the voice language."""
        self.voice_language = language

    def switch_model(self, model_info):
        """Switches the TTS model via the adapter."""
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

    # The `load_tts_model` method can remain as-is or be integrated into a different service.
    # It doesn't directly interact with the adapter, but rather manages the underlying process.
    def load_tts_model(self, gpt_sovits_work_path="C:\\AI\\GPT-SoVITS\\GPT-SoVITS-v2pro-20250604-nvidia50"):
        """Loads the TTS model by starting the server process."""
        os_path = gpt_sovits_work_path
        embeded_python_path = os_path + "\\runtime\\python.exe"
        path = os_path + "\\api_v2.py"
        subprocess.Popen([embeded_python_path, path], cwd=os_path)

    def shutdown(self):
        """Shuts down the queue and worker thread."""
        self.task_queue.put(None)
        self.worker_thread.join()
