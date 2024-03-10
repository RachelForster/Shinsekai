"""
先运行main.bat
"""
import requests

# 根据音频说话
data = {
    "type": "speak",
    "speech_path": r"data/speech/uri_speech_0.wav"  # 修改为你的语音音频路径
}

# # 根据音频节奏摇
# data = {
#     "type": "rhythm",
#     "music_path": r"data/music/Noisy Radio - Chipi Chipi Chapa Chapa.flac",  # 修改为你的音频路径
#     "beat": 1
# }

# # 根据音频和人声唱歌
# data = {
#     "type": "sing",
#     "music_path": r"data/song/不分手的恋爱-汪苏泷.MP3",  # 修改为原曲路径
#     "voice_path": r"data/song/不分手的恋爱-汪苏泷_voice.MP3",  # 修改为人声音频路径
#     "mouth_offset": 0.0,
#     "beat": 2
# }

res = requests.post('http://127.0.0.1:7888/alive', json=data)
print(res.json())
