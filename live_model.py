import json
import os
import requests
from multiprocessing import Value, Process, Queue
import time
# import wave
# import pyaudio
from ctypes import c_bool
from display.caption_display import CaptionDisplay
# from display.chat_display import ChatDisplay
import re
import librosa
import numpy as np
from scipy.io import wavfile
import shutil

import edge_tts
import asyncio
import time
import Play_mp3
import pygame

voice = 'zh-CN-YunjianNeural'
song_name_list = ['kusuriuri', '东云博士', '东云秋花鱼', '天使西纳奈Shinanai', '懒得改名字和头像']


# output = './ext2voicetest.mp3'


def generate_voice_data(speech_path):
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
    return voice_strengths, voice_times


async def my_function(data, output_path):
    question_text = data['text']
    tts = edge_tts.Communicate(text=question_text, voice=voice, rate="+10%")
    await tts.save(output_path)
    Play_mp3.play(output_path)


def error_talk(speech_path):
    shutil.copyfile(r'./speech_data/error-svc.wav', speech_path)
    voice_strengths, voice_times = generate_voice_data(speech_path)
    ret = {
        'speech_texts': ['出错', '了', '，我', '感觉', '我', '的', '脑子', '有点', '短路', '了'],
        'speech_times': [[0.0505, 0.6005], [0.6005, 1.238], [1.4505, 1.613], [1.613, 1.9505], [1.9755, 2.1255],
                         [2.1255, 2.2005000000000003], [2.213, 2.588], [2.588, 2.8755],
                         [2.888, 3.3129999999999997], [3.313, 3.5380000000000003]],
        'voice_strengths': voice_strengths,
        'voice_times': voice_times,
    }
    return ret


def get_speech(ret, url, speech_path, is_json=False):
    try:
        if not is_json:
            ret = ret.json()
        # response = requests.get(url + ret['address'])  # + '/speech_data/speech.wav'
        response = requests.post(url + '/speech_data', json={'address': ret['address']})
        with open(speech_path, 'wb') as f:
            f.write(response.content)
        f.close()
        ret['voice_strengths'], ret['voice_times'] = generate_voice_data(speech_path)
        return ret
    except Exception as ex:
        print(ex)
        return error_talk(speech_path)


class ChatBase:
    def __init__(self, url, read_qes, song_path, speech_path='speech_data'):
        self.input_queue = Queue(maxsize=1)
        self.url = url
        os.makedirs(speech_path, exist_ok=True)
        self.speech_path = os.path.join(speech_path, 'speech.wav')
        self.question_tts_path = os.path.join(speech_path, 'question.mp3')
        self.read_qes = read_qes
        self.is_speech = Value(c_bool, False)
        self.speech_q = Queue()
        self.caption_display = CaptionDisplay()
        self.chunk = 1024  # 每次读取的帧数

        self.busy = Value(c_bool, False)

        self.song_path = song_path
        self.is_singing = Value(c_bool, False)
        self.beat_q = Queue()
        self.mouth_q = Queue()

    def chat_response(self, data):
        if data['text'][:3] == '唱歌：' and data['uname_color']:
            self.sing(data)
        else:
            self.chat_stream(data)

    def chat_start(self):
        self.busy.value = True

    def chat_end(self):
        self.busy.value = False

    def chat_stream(self, data):
        self.chat_start()
        try:
            # req_json = {'msg': data['text'], 'add2history': data['add2history']}
            with requests.post(self.url + '/chatai_stream_v1', json=data, stream=True, timeout=6) as ret:  #
                self.caption_display.query.put_nowait(data)
                if self.read_qes and data['nickname'] != '东云博士':
                    asyncio.run(my_function(data, self.question_tts_path))
                    # print('question done')

                ret_bits = ''.encode('utf-8')
                cur_idx = 0
                for r in ret:
                    if ret.status_code != 200:
                        self.speech_start()
                        break
                    ret_bits = ret_bits + r
                    ret_json = ret_bits.decode(encoding='utf-8', errors='ignore')
                    end_idx = ret_json[cur_idx:].find('}')
                    while end_idx != -1:
                        self.speech_start(ret=json.loads(ret_json[cur_idx:cur_idx + end_idx + 1].replace('#)#', '}')), is_json=True)
                        cur_idx = cur_idx + end_idx + 1
                        end_idx = ret_json[cur_idx:].find('}')
        except Exception as ex:
            print('error', ex)
            self.speech_start()
        self.chat_end()

    def chat(self, data):
        self.chat_start()
        req_json = {'msg': data['text'], 'add2history': data['add2history']}
        ret = requests.post(self.url + '/chatai', json=req_json)
        self.caption_display.query.put_nowait(data)
        self.speech_start(ret=ret)
        self.chat_end()

    def speech_start(self, ret=None, is_json=False):
        if not ret:
            ret = error_talk(self.speech_path)
        else:
            ret = get_speech(ret, self.url, self.speech_path, is_json=is_json)

        # # 播放
        # wf = wave.open(self.speech_path, 'rb')
        # p = pyaudio.PyAudio()
        # stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
        #                 channels=wf.getnchannels(),
        #                 rate=wf.getframerate(),
        #                 output=True)
        # data = wf.readframes(self.chunk)
        ret['speech_times'] = np.array(ret['speech_times']) + time.perf_counter() - 0.15
        ret['voice_times'] = np.array(ret['voice_times']) + time.perf_counter() - 0.15
        self.caption_display.text_q.put_nowait(ret)
        self.speech_q.put_nowait(ret)
        self.is_speech.value = True
        # while len(data) > 0:
        #     stream.write(data)
        #     data = wf.readframes(self.chunk)
        # stream.stop_stream()
        # stream.close()

        # 播放
        pygame.mixer.init()
        pygame.mixer.music.load(self.speech_path)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():  # 在音频播放为完成之前不退出程序
            time.sleep(0.1)  # 减轻循环负担
        pygame.quit()
        self.is_speech.value = False

    def sing(self, data):
        self.chat_start()
        self.caption_display.query.put_nowait(data)
        music_name = data['text'][3:]
        have_music = False
        for music in os.listdir(self.song_path):
            if music == music_name:
                have_music = True
                music_info = json.load(
                    open(os.path.join(self.song_path, music, f'{music}.json'), 'r', encoding='utf-8'))
                text = f"歌曲：{music}  原声：{music_info['src_voice']}"
                self.caption_display.text_q.put_nowait({'speech_texts': [text],
                                                        'speech_times': [
                                                            [time.perf_counter(), time.perf_counter() + 1]]})
                try:
                    # # 播放
                    # wf = wave.open(os.path.join(self.song_path, music, f'{music}.wav'), 'rb')
                    # p = pyaudio.PyAudio()
                    # stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                    #                 channels=wf.getnchannels(),
                    #                 rate=wf.getframerate(),
                    #                 output=True)
                    # music_data = wf.readframes(self.chunk)
                    self.beat_q.put_nowait(
                        {'beat_times': np.array(music_info['beat_times']) + time.perf_counter() - 0.15,
                         'beat_strengths': music_info['beat_strengths']})
                    self.mouth_q.put_nowait(
                        {'voice_times': np.array(music_info['voice_times']) + time.perf_counter() - 0.15,
                         'voice_strengths': music_info['voice_strengths']})
                    self.is_singing.value = True
                    # while len(music_data) > 0 and self.is_singing.value:
                    #     # print(self.is_singing.value)
                    #     stream.write(music_data)
                    #     music_data = wf.readframes(self.chunk)
                    # stream.stop_stream()
                    # stream.close()

                    # 播放
                    pygame.mixer.init()
                    pygame.mixer.music.load(os.path.join(self.song_path, music, f'{music}.wav'))
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy() and self.is_singing.value:  # 在音频播放为完成之前不退出程序
                        time.sleep(0.1)  # 减轻循环负担
                    pygame.quit()
                    self.is_singing.value = False
                except Exception as ex:
                    print(ex)
                    self.speech_start()
        if not have_music:
            text = f"没有{music_name}"
            self.caption_display.text_q.put_nowait({'speech_texts': [text],
                                                    'speech_times': [[time.perf_counter(), time.perf_counter() + 1]]})
            time.sleep(3)

        self.chat_end()


class ChatModel(Process, ChatBase):
    def __init__(self, url, read_qes, song_path):
        super().__init__()
        ChatBase.__init__(self, url, read_qes, song_path)

    def run(self):
        self.caption_display.start()
        while True:
            data = self.input_queue.get()
            self.chat_response(data)


class ChatMusicModel(Process, ChatBase):
    def __init__(self, url, read_qes, song_path, music_path='music_data'):
        super().__init__()
        ChatBase.__init__(self, url, read_qes, song_path)
        self.is_music_play = Value(c_bool, False)
        os.makedirs(music_path, exist_ok=True)
        self.music_path = os.path.join(music_path, 'music.wav')
        self.beat_q = Queue()
        self.min_duration = 3
        self.max_duration = 10

    def run(self):
        self.caption_display.start()
        while True:
            data = self.input_queue.get()
            # #desc#dulation
            if data['text'][:1] == "#":
                if self.check_music_info(data):
                    self.music_gen(data)
            else:
                # self.chat(data)
                self.chat_response(data)

    # def only_talk(self, data, ans):
    #     self.caption_display.query.put_nowait(data)
    #     self.chat_start()
    #     try:
    #         ret = requests.post(self.url + '/tts', json={'msg': ans})
    #         self.speech_start(ret=ret)
    #     except Exception as ex:
    #         print(ex)
    #         self.speech_start()
    #     self.chat_end()

    def check_music_info(self, data):
        flag = False
        data_, nickname = data['text'].split('#'), data['nickname']
        data['add_query'] = False
        if re.search('[\u4e00-\u9fa5]+', data_[1]):
            data['response'] = f"{nickname}，描述一定要是英文哦"
            self.chat_stream(data)
        elif len(data_) != 3:
            data['response'] = f"{nickname}，格式不对哦"
            self.chat_stream(data)
        elif not data_[2].isdigit():
            data['response'] = f"{nickname}，时间要是正整数哦"
            self.chat_stream(data)
        else:
            flag = True
        return flag

    def music_gen(self, data):
        data_ = data['text'].split('#')
        desc, duration = data_[1], min(max(int(data_[2]), self.min_duration), self.max_duration)
        desc = re.sub('[^a-zA-Z1-9,.!?(){} ]', '', desc)
        text = f"接下来创作一段{duration}秒的{desc}"
        data['response'] = text
        data['add_query'] = False
        self.chat_stream(data)

        # text = f"...正在创作{desc}..."
        # self.caption_display.text_q.put_nowait({'speech_texts': [text],
        #                                         'speech_times': [[time.perf_counter(), time.perf_counter() + 1]]})
        # self.chat_start()
        try:
            ret = requests.post(self.url + '/plugin_server', json={'msg': desc, 'duration': duration})
            with open(self.music_path, 'wb') as f:
                f.write(ret.content)

            # 淡入淡出
            sr, music_data = wavfile.read(self.music_path)
            factors = np.arange(sr) / sr
            factors = np.concatenate([factors, np.ones(len(music_data) - 2 * sr), factors[::-1]])
            music_data = music_data * factors
            music_data = np.clip(music_data, -32767, 32767)
            wavfile.write(self.music_path, sr, music_data.astype(np.int16))

            # 提取节奏点，节奏强度
            y, sr = librosa.load(self.music_path)
            tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
            beat_times = librosa.frames_to_time(beat_frames, sr=sr)
            beat_times = np.concatenate([[0], beat_times])
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            frame_intervals = int(len(y) / len(onset_env))
            beat_strengths = np.array([np.max(y[i:i + frame_intervals])
                                       for i in range(frame_intervals // 2, len(y), frame_intervals)])
            beat_strengths = np.clip(beat_strengths[beat_frames], 0., 1.)

            # 播放
            # wf = wave.open(self.music_path, 'rb')
            # p = pyaudio.PyAudio()
            # stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
            #                 channels=wf.getnchannels(),
            #                 rate=wf.getframerate(),
            #                 output=True)
            # music_data = wf.readframes(self.chunk)
            self.beat_q.put_nowait({'beat_times': beat_times + time.perf_counter() - 0.15,
                                    'beat_strengths': beat_strengths})
            self.is_music_play.value = True
            # while len(music_data) > 0:
            #     stream.write(music_data)
            #     music_data = wf.readframes(self.chunk)
            # stream.stop_stream()
            # stream.close()

            # 播放
            pygame.mixer.init()
            pygame.mixer.music.load(self.music_path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():  # 在音频播放为完成之前不退出程序
                time.sleep(0.1)  # 减轻循环负担
            pygame.quit()
            self.is_music_play.value = False
        except Exception as ex:
            print(ex)
            self.speech_start()


# 如果bilibili_api用不了就要考虑用回这个方法
# class BilibiliBarrageProcess(Process):
#     def __init__(self, room_id, chat_url, chat_mode='chat'):
#         super().__init__()
#         self.url = rf'http://api.live.bilibili.com/ajax/msg?roomid={room_id}'
#         self.barrage_history = [{'uid': -1, 'nickname': '', 'timeline': '', 'text': ''}]
#         self.barrage_max_len = 20
#         self.input_queue_max_len = 1
#         if chat_mode == 'chat':
#             self.model_process = ChatModel(chat_url)
#         elif chat_mode == 'music':
#             self.model_process = ChatMusicModel(chat_url)
#         elif chat_mode == 'video':
#             pass
#         else:
#             raise ValueError('dont support mode!')
#
#         self.chat_display = ChatDisplay()
#
#         self.debug = DeBug()
#
#     def run(self):
#         self.model_process.start()
#         self.chat_display.start()
#         self.debug.start()
#
#         while True:
#             res = requests.get(self.url).json()
#             data = res['data']['room']
#             new_num = 0
#             for i in range(len(data)-1, -1, -1):
#                 if data[i] == self.barrage_history[-1]:
#                     break
#                 new_num += 1
#             for data_ in data[len(data)-new_num:]:
#                 self.barrage_history.append(data_)
#                 if len(self.barrage_history) > self.barrage_max_len:
#                     self.barrage_history.pop(0)
#                 self.chat_display.chat_list_q.put_nowait(data_)
#                 if data_ == data[-1]:
#                     self.model_process.input_queue.put_nowait(data_)
#
#             if not self.debug.query.empty():
#                 self.model_process.input_queue.put_nowait(self.debug.query.get_nowait())
#
#             while self.model_process.input_queue.qsize() > self.input_queue_max_len:
#                 self.model_process.input_queue.get_nowait()
#
#             time.sleep(0.5)
