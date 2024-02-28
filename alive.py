import os
import numpy as np
from multiprocessing import Value, Process, Queue
from ctypes import c_bool
import librosa
import time
import pygame


def generate_voice_data(speech_path):
    ret = {}
    # 提取节奏强度
    time_ratio = 0.06
    y, sr = librosa.load(speech_path)
    frame_intervals = int(sr * time_ratio)
    voice_strengths = np.array([np.max(y[i:i + frame_intervals]) for i in range(0, len(y), frame_intervals)])
    voice_strengths = np.clip(voice_strengths, 0., 1.).tolist()
    voice_strengths = [round(vst, 2) for i, vst in enumerate(voice_strengths)]
    voice_times = [0]
    last = time_ratio
    for i in range(len(voice_strengths)):
        voice_times.append(round(last, 1))
        last += time_ratio
    ret['voice_strengths'], ret['voice_times'] = voice_strengths, voice_times
    return ret


class Alive(Process):
    def __init__(self, alive_args):  #
        super().__init__()
        self.is_speech = alive_args['is_speech']
        self.speech_q = alive_args['speech_q']

        self.is_singing = alive_args['is_singing']
        self.beat_q = alive_args['beat_q']
        self.mouth_q = alive_args['mouth_q']

    def speak(self, speech_path):
        ret = generate_voice_data(speech_path)
        ret['voice_times'] = np.array(ret['voice_times']) + time.perf_counter() - 0.15
        self.speech_q.put_nowait(ret)
        self.is_speech.value = True

        # 播放
        pygame.mixer.init()
        pygame.mixer.music.load(speech_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():  # 在音频播放为完成之前不退出程序
            time.sleep(0.1)  # 减轻循环负担
        pygame.quit()
        self.is_speech.value = False

    # def sing(self, song_path):
    #     if not os.path.exists(song_path):
    #         print(f"找不到{song_path}")
    #         return
    #
    #     self.beat_q.put_nowait(
    #         {'beat_times': np.array(music_info['beat_times']) + time.perf_counter() - 0.15,
    #          'beat_strengths': music_info['beat_strengths']})
    #     self.mouth_q.put_nowait(
    #         {'voice_times': np.array(music_info['voice_times']) + time.perf_counter() - 0.15,
    #          'voice_strengths': music_info['voice_strengths']})
    #     self.is_singing.value = True
    #
    #     # 播放
    #     pygame.mixer.init()
    #     pygame.mixer.music.load(song_path)
    #     pygame.mixer.music.play()
    #     while pygame.mixer.music.get_busy() and self.is_singing.value:  # 在音频播放为完成之前不退出程序
    #         time.sleep(0.1)  # 减轻循环负担
    #     pygame.quit()
    #     self.is_singing.value = False


