"""
先运行main.bat
"""

import requests

data = {
    "type": "speak",
    "speech_path": r".\speech_data\uri_speech_0.wav"
}

print(requests.post('http://127.0.0.1:7888/alive', json=data).json())
