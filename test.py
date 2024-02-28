"""
先运行main.bat
"""

import requests

data = {
    "type": "speak",  # 说话动作
    "speech_path": r".\speech_data\uri_speech_0.wav"  # 语音音频路径
}

print(requests.post('http://127.0.0.1:7888/alive', json=data).json())
