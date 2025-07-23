import torch
import cv2
import numpy as np
from PIL import Image

import tha2.poser.modes.mode_20_wx
from models import TalkingAnime3
from utils import preprocessing_image
from action_animeV2 import ActionAnimeV2
from alive import Alive
from multiprocessing import Value, Process, Queue
from ctypes import c_bool
from llm.deepseek import DeepSeek
import os

import queue
import time
import math
import collections
from collections import OrderedDict
from args import args
from tha3.util import torch_linear_to_srgb
from pyanime4k import ac

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

fps_delay = 0.01

from flask import Flask
from flask_restful import Resource, Api, reqparse

import sys
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QRect
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLineEdit, QSizePolicy

app = Flask(__name__)
api = Api(app)

global deepseek

def convert_linear_to_srgb(image: torch.Tensor) -> torch.Tensor:
    rgb_image = torch_linear_to_srgb(image[0:3, :, :])
    return torch.cat([rgb_image, image[3:4, :, :]], dim=0)


class FPS:
    def __init__(self, avarageof=50):
        self.frametimestamps = collections.deque(maxlen=avarageof)

    def __call__(self):
        self.frametimestamps.append(time.time())
        if len(self.frametimestamps) > 1:
            return len(self.frametimestamps) / (self.frametimestamps[-1] - self.frametimestamps[0])
        else:
            return 0.0


ifm_converter = tha2.poser.modes.mode_20_wx.IFacialMocapPoseConverter20()


class ModelClientProcess(Process):
    def __init__(self, input_image, device, model_process_args):
        super().__init__()
        self.device = device
        self.should_terminate = Value('b', False)
        self.updated = Value('b', False)
        self.data = None
        self.input_image = input_image
        self.output_queue = model_process_args['output_queue']
        self.input_queue = model_process_args['input_queue']
        self.model_fps_number = Value('f', 0.0)
        self.gpu_fps_number = Value('f', 0.0)
        self.cache_hit_ratio = Value('f', 0.0)
        self.gpu_cache_hit_ratio = Value('f', 0.0)

        self.input_image_q = model_process_args['input_image_q']

    def run(self):
        model = TalkingAnime3().to(self.device)
        model = model.eval()
        print("Pretrained Model Loaded")

        eyebrow_vector = torch.empty(1, 12, dtype=torch.half if args.model.endswith('half') else torch.float)
        mouth_eye_vector = torch.empty(1, 27, dtype=torch.half if args.model.endswith('half') else torch.float)
        pose_vector = torch.empty(1, 6, dtype=torch.half if args.model.endswith('half') else torch.float)

        input_image = self.input_image.to(self.device)
        eyebrow_vector = eyebrow_vector.to(self.device)
        mouth_eye_vector = mouth_eye_vector.to(self.device)
        pose_vector = pose_vector.to(self.device)

        model_cache = OrderedDict()
        tot = 0
        hit = 0
        hit_in_a_row = 0
        model_fps = FPS()
        gpu_fps = FPS()
        cur_sec = int(time.perf_counter())
        fps_num = 0
        while True:
            # time.sleep(fps_delay)
            if int(time.perf_counter()) == cur_sec:
                fps_num += 1
            else:
                # print(fps_num)
                fps_num = 0
                cur_sec = int(time.perf_counter())

            if not self.input_image_q.empty():
                input_image = self.input_image_q.get_nowait().to(self.device)
                model.face_cache = OrderedDict()
                model_cache = OrderedDict()

            model_input = None
            try:
                while not self.input_queue.empty():
                    model_input = self.input_queue.get_nowait()
            except queue.Empty:
                continue
            if model_input is None:
                continue
            simplify_arr = [1000] * ifm_converter.pose_size
            if args.simplify >= 1:
                simplify_arr = [200] * ifm_converter.pose_size
                simplify_arr[ifm_converter.eye_wink_left_index] = 50
                simplify_arr[ifm_converter.eye_wink_right_index] = 50
                simplify_arr[ifm_converter.eye_happy_wink_left_index] = 50
                simplify_arr[ifm_converter.eye_happy_wink_right_index] = 50
                simplify_arr[ifm_converter.eye_surprised_left_index] = 30
                simplify_arr[ifm_converter.eye_surprised_right_index] = 30
                simplify_arr[ifm_converter.iris_rotation_x_index] = 25
                simplify_arr[ifm_converter.iris_rotation_y_index] = 25
                simplify_arr[ifm_converter.eye_raised_lower_eyelid_left_index] = 10
                simplify_arr[ifm_converter.eye_raised_lower_eyelid_right_index] = 10
                simplify_arr[ifm_converter.mouth_lowered_corner_left_index] = 5
                simplify_arr[ifm_converter.mouth_lowered_corner_right_index] = 5
                simplify_arr[ifm_converter.mouth_raised_corner_left_index] = 5
                simplify_arr[ifm_converter.mouth_raised_corner_right_index] = 5
            if args.simplify >= 2:
                simplify_arr[ifm_converter.head_x_index] = 100
                simplify_arr[ifm_converter.head_y_index] = 100
                simplify_arr[ifm_converter.eye_surprised_left_index] = 10
                simplify_arr[ifm_converter.eye_surprised_right_index] = 10
                model_input[ifm_converter.eye_wink_left_index] += model_input[
                    ifm_converter.eye_happy_wink_left_index]
                model_input[ifm_converter.eye_happy_wink_left_index] = model_input[
                                                                           ifm_converter.eye_wink_left_index] / 2
                model_input[ifm_converter.eye_wink_left_index] = model_input[
                                                                     ifm_converter.eye_wink_left_index] / 2
                model_input[ifm_converter.eye_wink_right_index] += model_input[
                    ifm_converter.eye_happy_wink_right_index]
                model_input[ifm_converter.eye_happy_wink_right_index] = model_input[
                                                                            ifm_converter.eye_wink_right_index] / 2
                model_input[ifm_converter.eye_wink_right_index] = model_input[
                                                                      ifm_converter.eye_wink_right_index] / 2

                uosum = model_input[ifm_converter.mouth_uuu_index] + \
                        model_input[ifm_converter.mouth_ooo_index]
                model_input[ifm_converter.mouth_ooo_index] = uosum
                model_input[ifm_converter.mouth_uuu_index] = 0
                is_open = (model_input[ifm_converter.mouth_aaa_index] + model_input[
                    ifm_converter.mouth_iii_index] + uosum) > 0
                model_input[ifm_converter.mouth_lowered_corner_left_index] = 0
                model_input[ifm_converter.mouth_lowered_corner_right_index] = 0
                model_input[ifm_converter.mouth_raised_corner_left_index] = 0.5 if is_open else 0
                model_input[ifm_converter.mouth_raised_corner_right_index] = 0.5 if is_open else 0
                simplify_arr[ifm_converter.mouth_lowered_corner_left_index] = 0
                simplify_arr[ifm_converter.mouth_lowered_corner_right_index] = 0
                simplify_arr[ifm_converter.mouth_raised_corner_left_index] = 0
                simplify_arr[ifm_converter.mouth_raised_corner_right_index] = 0
            if args.simplify >= 3:
                simplify_arr[ifm_converter.iris_rotation_x_index] = 20
                simplify_arr[ifm_converter.iris_rotation_y_index] = 20
                simplify_arr[ifm_converter.eye_wink_left_index] = 32
                simplify_arr[ifm_converter.eye_wink_right_index] = 32
                simplify_arr[ifm_converter.eye_happy_wink_left_index] = 32
                simplify_arr[ifm_converter.eye_happy_wink_right_index] = 32
            if args.simplify >= 4:
                simplify_arr[ifm_converter.head_x_index] = 50
                simplify_arr[ifm_converter.head_y_index] = 50
                simplify_arr[ifm_converter.neck_z_index] = 100
                model_input[ifm_converter.eye_raised_lower_eyelid_left_index] = 0
                model_input[ifm_converter.eye_raised_lower_eyelid_right_index] = 0
                simplify_arr[ifm_converter.iris_rotation_x_index] = 10
                simplify_arr[ifm_converter.iris_rotation_y_index] = 10
                simplify_arr[ifm_converter.eye_wink_left_index] = 24
                simplify_arr[ifm_converter.eye_wink_right_index] = 24
                simplify_arr[ifm_converter.eye_happy_wink_left_index] = 24
                simplify_arr[ifm_converter.eye_happy_wink_right_index] = 24
                simplify_arr[ifm_converter.eye_surprised_left_index] = 8
                simplify_arr[ifm_converter.eye_surprised_right_index] = 8
                model_input[ifm_converter.eye_wink_left_index] += model_input[
                    ifm_converter.eye_wink_right_index]
                model_input[ifm_converter.eye_wink_right_index] = model_input[
                                                                      ifm_converter.eye_wink_left_index] / 2
                model_input[ifm_converter.eye_wink_left_index] = model_input[
                                                                     ifm_converter.eye_wink_left_index] / 2

                model_input[ifm_converter.eye_surprised_left_index] += model_input[
                    ifm_converter.eye_surprised_right_index]
                model_input[ifm_converter.eye_surprised_right_index] = model_input[
                                                                           ifm_converter.eye_surprised_left_index] / 2
                model_input[ifm_converter.eye_surprised_left_index] = model_input[
                                                                          ifm_converter.eye_surprised_left_index] / 2

                model_input[ifm_converter.eye_happy_wink_left_index] += model_input[
                    ifm_converter.eye_happy_wink_right_index]
                model_input[ifm_converter.eye_happy_wink_right_index] = model_input[
                                                                            ifm_converter.eye_happy_wink_left_index] / 2
                model_input[ifm_converter.eye_happy_wink_left_index] = model_input[
                                                                           ifm_converter.eye_happy_wink_left_index] / 2
                model_input[ifm_converter.mouth_aaa_index] = min(
                    model_input[ifm_converter.mouth_aaa_index] +
                    model_input[ifm_converter.mouth_ooo_index] / 2 +
                    model_input[ifm_converter.mouth_iii_index] / 2 +
                    model_input[ifm_converter.mouth_uuu_index] / 2, 1
                )
                model_input[ifm_converter.mouth_ooo_index] = 0
                model_input[ifm_converter.mouth_iii_index] = 0
                model_input[ifm_converter.mouth_uuu_index] = 0
            for i in range(4, args.simplify):
                simplify_arr = [max(math.ceil(x * 0.8), 5) for x in simplify_arr]
            for i in range(0, len(simplify_arr)):
                if simplify_arr[i] > 0:
                    model_input[i] = round(model_input[i] * simplify_arr[i]) / simplify_arr[i]
            input_hash = hash(tuple(model_input))
            cached = model_cache.get(input_hash)
            tot += 1
            eyebrow_vector_c = [0.0] * 12
            mouth_eye_vector_c = [0.0] * 27
            if cached is not None and hit_in_a_row < self.model_fps_number.value:
                self.output_queue.put(cached)
                model_cache.move_to_end(input_hash)
                hit += 1
                hit_in_a_row += 1
            else:
                hit_in_a_row = 0
                if args.eyebrow:
                    for i in range(12):
                        eyebrow_vector[0, i] = model_input[i]
                        eyebrow_vector_c[i] = model_input[i]
                for i in range(27):
                    mouth_eye_vector[0, i] = model_input[i + 12]
                    mouth_eye_vector_c[i] = model_input[i + 12]
                for i in range(6):
                    pose_vector[0, i] = model_input[i + 27 + 12]
                if model is None:
                    output_image = input_image
                else:
                    output_image = model(input_image, mouth_eye_vector, pose_vector, eyebrow_vector, mouth_eye_vector_c,
                                         eyebrow_vector_c,
                                         self.gpu_cache_hit_ratio)
                postprocessed_image = output_image[0].float()
                postprocessed_image = convert_linear_to_srgb((postprocessed_image + 1.0) / 2.0)
                c, h, w = postprocessed_image.shape
                postprocessed_image = 255.0 * torch.transpose(postprocessed_image.reshape(c, h * w), 0, 1).reshape(h, w,
                                                                                                                   c)
                postprocessed_image = postprocessed_image.byte().detach().cpu().numpy()

                self.output_queue.put(postprocessed_image)
                if args.debug:
                    self.gpu_fps_number.value = gpu_fps()
                if args.max_cache_len > 0:
                    model_cache[input_hash] = postprocessed_image
                    if len(model_cache) > args.max_cache_len:
                        model_cache.popitem(last=False)
            if args.debug:
                self.model_fps_number.value = model_fps()
                self.cache_hit_ratio.value = hit / tot


def prepare_input_img(IMG_WIDTH, charc):
    if os.path.exists(charc):
        img = Image.open(charc)
    else:
        img = Image.open(f"data/images/{charc}.png")
    img = img.convert('RGBA')
    wRatio = img.size[0] / IMG_WIDTH
    img = img.resize((IMG_WIDTH, int(img.size[1] / wRatio)))
    for i, px in enumerate(img.getdata()):
        if px[3] <= 0:
            y = i // IMG_WIDTH
            x = i % IMG_WIDTH
            img.putpixel((x, y), (0, 0, 0, 0))
    input_image = preprocessing_image(img.crop((0, 0, IMG_WIDTH, IMG_WIDTH)))
    if args.model.endswith('half'):
        input_image = torch.from_numpy(input_image).half() * 2.0 - 1
    else:
        input_image = torch.from_numpy(input_image).float() * 2.0 - 1
    input_image = input_image.unsqueeze(0)
    extra_image = None
    if img.size[1] > IMG_WIDTH:
        extra_image = np.array(img.crop((0, IMG_WIDTH, img.size[0], img.size[1])))
    print("Character Image Loaded:", charc)
    return input_image, extra_image

# 新增类：图像显示线程
class ImageDisplayThread(QThread):
    update_signal = pyqtSignal(np.ndarray)
    
    def __init__(self, image_queue):
        super().__init__()
        self.image_queue = image_queue
        self.running = True
        
    def run(self):
        while self.running:
            try:
                if not self.image_queue.empty():
                    image = self.image_queue.get()
                    self.update_signal.emit(image)
                QThread.msleep(10)  # 10ms刷新间隔
            except Exception as e:
                print(f"Display error: {e}")
    
    def stop(self):
        self.running = False


class ChatWorker(QThread):
    response_received = pyqtSignal(str, str)  # 定义信号用于传递响应
    
    def __init__(self, deepseek, message):
        super().__init__()
        self.deepseek = deepseek
        self.message = message
    
    def run(self):
        """在后台线程中执行聊天请求"""
        message, emotion = self.deepseek.chat(self.message)
        self.deepseek.get_voice(message)  # 调用DeepSeek的音频发送方法
        self.response_received.emit(message, emotion)

class DesktopAssistantWindow(QWidget):
    def __init__(self, image_queue, emotion_queue, deepseek):
        super().__init__()
        self.image_queue = image_queue
        self.deepseek = deepseek
        self.emotion_queue = emotion_queue

        self.chat_worker = None  # 用于处理聊天请求的工作线程
        self.original_width = 1536

        # 窗口设置
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)

        # 使用一个容器来放置图像和对话框
        self.image_container = QWidget()
        self.image_layout = QVBoxLayout(self.image_container)
        self.image_layout.setContentsMargins(0, 0, 0, 0)
        self.image_layout.setSpacing(0)

        # 添加对话框组件 - 显示人物当前说的话
        self.dialog_label = QLabel("")
        self.dialog_label.setTextFormat(Qt.RichText)
        self.dialog_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)  # 文本从顶部开始
        self.dialog_label.setStyleSheet("""
        QLabel {
            background-color: rgba(50, 50, 50, 200);
            color: #f0f0f0;  /* 柔和的白色 */
            font-size: 36px;
            font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
            padding: 20px; 
            border-radius: 12px;
            border-bottom-left-radius: 0;
            border-bottom-right-radius: 0;
            line-height: 200%;
            letter-spacing: 2px;  /* 增加字间距 */
        }
        """)
        self.dialog_label.setWordWrap(True)
        self.dialog_label.hide()

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)  # 添加尺寸策略
        self.image_layout.addWidget(self.label)

        # 将对话框添加到图像容器中（覆盖在图像上方）
        self.dialog_label.setParent(self.image_container)

        # 输入框布局
        input_layout = QHBoxLayout()
        input_layout.setSpacing(10)
        
        # 输入框组件
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("输入消息...")
        self.input_box.setStyleSheet("""
            QLineEdit {
                background-color: rgba(50, 50, 50, 200);
                color: white;
                font-family: 'Microsoft YaHei', 'SimHei', 'Arial';
                border: 1px solid #555;
                border-radius: 5px;
                padding: 20px;
                font-size: 28px;
            }
        """)
        self.input_box.returnPressed.connect(self.sendMessage)
        
        # 发送按钮
        self.send_btn = QPushButton("发送")
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px;
                font-size: 28px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.send_btn.clicked.connect(self.sendMessage)
        
        input_layout.addWidget(self.input_box)
        input_layout.addWidget(self.send_btn)
        
        # 将组件添加到主布局
        main_layout.addWidget(self.image_container)
        main_layout.addLayout(input_layout)
        
        self.setLayout(main_layout)
        
        # 设置图像显示线程
        self.display_thread = ImageDisplayThread(image_queue)
        self.display_thread.update_signal.connect(self.update_image)
        self.display_thread.start()
        
        # 初始大小
        self.resize(self.original_width, self.original_width)
        
        # 交互设置
        self.drag_position = None
        
    def update_image(self, image):
        """更新显示图像"""
        self.original_image = image  # 保存原始图像
        height, width, channel = image.shape
        bytes_per_line = 4 * width
        qimg = QImage(image.data, width, height, bytes_per_line, QImage.Format_RGBA8888)
        pixmap = QPixmap.fromImage(qimg)
        
        # 将图像放大
        rate = self.original_width / 1024
        scaled_pixmap = pixmap.scaled(
            int(width * rate), 
            int(height * rate),
            Qt.KeepAspectRatio, 
            Qt.SmoothTransformation
        )
        
        # 设置放大后的图像
        self.label.setPixmap(scaled_pixmap)
        
        # 调整QLabel大小以匹配图像尺寸
        self.label.setFixedSize(self.original_width, self.original_width)

        # 调整窗口大小以适应内容
        self.adjustSize()
    
    def sendMessage(self):
        """发送消息函数"""
        message = self.input_box.text().strip()
        if message:
            print(f"发送消息: {message}")
            # 清空输入框
            self.input_box.clear()
            
            # 可选: 在对话框中显示用户发送的消息
            self.setDisplayWords(f"<b>你</b>：{message}")

            # 创建并启动聊天工作线程
            self.chat_worker = ChatWorker(self.deepseek, message)
            self.chat_worker.response_received.connect(self.handleResponse)  # 连接信号
            self.chat_worker.start()  # 启动线程
    
    def handleResponse(self, message, emotion):
        """处理聊天响应"""
        # 在对话框中显示AI的回复
        self.setDisplayWords(f"<p style='line-height: 135%; letter-spacing: 2px;'><b style='color: #A7CA90;'>狛枝凪斗</b>：{message}</p>")
        if not self.emotion_queue.full():
            self.emotion_queue.put(emotion)

    def setDisplayWords(self, text):
        """显示人物说的话"""
        if text:
            self.dialog_label.setText(text)
            self.dialog_label.show()
            
            # 调整对话框大小以适应文本
            self.dialog_label.adjustSize()
            
            # 设置对话框位置
            y = self.label.height() - self.dialog_label.height()  # 从底部开始
            
            # 设置对话框几何位置
            self.dialog_label.setGeometry(0, y, self.label.width(), self.dialog_label.height())

        else:
            self.dialog_label.hide()
       
    def mousePressEvent(self, event):
        """实现窗口拖动"""
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
    
    def mouseMoveEvent(self, event):
        """拖动窗口"""
        if event.buttons() == Qt.LeftButton and self.drag_position:
            self.move(event.globalPos() - self.drag_position)
            event.accept()
    
    def closeEvent(self, event):
        """关闭窗口时停止线程"""
        self.display_thread.stop()
        self.display_thread.wait()
        super().closeEvent(event)

class EasyAIV(Process):  #
    def __init__(self, model_process_args, alive_args):
        super().__init__()
        # self.extra_image = extra_image

        self.model_process_input_queue = model_process_args['input_queue']
        self.model_process_output_queue = model_process_args['output_queue']

        self.alive_args_is_speech = alive_args['is_speech']
        self.alive_args_speech_q = alive_args['speech_q']

        self.alive_args_is_singing = alive_args['is_singing']
        self.alive_args_is_music_play = alive_args['is_music_play']
        self.alive_args_beat_q = alive_args['beat_q']
        self.alive_args_mouth_q = alive_args['mouth_q']
    @staticmethod
    def start_qt_app(display_queue, emotion_queue):
        """启动PyQt应用"""
        app = QApplication(sys.argv)
        deepseek = DeepSeek()
        window = DesktopAssistantWindow(display_queue, emotion_queue, deepseek)
        print("QT Window starts!!")
        window.show()
        sys.exit(app.exec_())


    @torch.no_grad()
    def run(self):
        IMG_WIDTH = 512
        
        # 添加图像显示队列
        display_queue = Queue(maxsize=3)  # 最大缓存3帧

        # 情绪显示队列
        emotion_queue = Queue(maxsize=3)
        
        qt_process = Process(
            target=EasyAIV.start_qt_app,
            args=(display_queue, emotion_queue)
        )
        qt_process.daemon = True
        qt_process.start()

        a = None
        if args.anime4k:
            parameters = ac.Parameters()
            # enable HDN for ACNet
            parameters.HDN = True

            a = ac.AC(
                managerList=ac.ManagerList([ac.OpenCLACNetManager(pID=0, dID=0)]),
                type=ac.ProcessorType.OpenCL_ACNet,
            )
            a.set_arguments(parameters)
            print("Anime4K Loaded")

        position_vector = [0, 0, 0, 1]

        model_output = None

        speech_q = None
        mouth_q = None
        beat_q = None

        action = ActionAnimeV2()
        idle_start_time = time.perf_counter()

        print("Ready. Close this console to exit.")

        while True:
            # time.sleep(fps_delay)

            idle_flag = False
            if bool(self.alive_args_is_speech.value):  # 正在说话
                if not emotion_queue.empty():
                    action.setEmotion(emotion_queue.get_nowait())
                if not self.alive_args_speech_q.empty():
                    speech_q = self.alive_args_speech_q.get_nowait()
                eyebrow_vector_c, mouth_eye_vector_c, pose_vector_c = action.speaking(speech_q)
            elif bool(self.alive_args_is_singing.value):  # 正在唱歌
                if not self.alive_args_beat_q.empty():
                    beat_q = self.alive_args_beat_q.get_nowait()
                if not self.alive_args_mouth_q.empty():
                    mouth_q = self.alive_args_mouth_q.get_nowait()
                eyebrow_vector_c, mouth_eye_vector_c, pose_vector_c = action.singing(beat_q, mouth_q)
            elif bool(self.alive_args_is_music_play.value):  # 摇子
                if not self.alive_args_beat_q.empty():
                    beat_q = self.alive_args_beat_q.get_nowait()
                eyebrow_vector_c, mouth_eye_vector_c, pose_vector_c = action.rhythm(beat_q)
            else:  # 空闲状态
                speech_q = None
                mouth_q = None
                beat_q = None
                idle_flag = True
                if args.sleep != -1 and time.perf_counter() - idle_start_time > args.sleep:  # 空闲20秒就睡大觉
                    eyebrow_vector_c, mouth_eye_vector_c, pose_vector_c = action.sleeping()
                else:
                    eyebrow_vector_c, mouth_eye_vector_c, pose_vector_c = action.idle()

            if not idle_flag:
                idle_start_time = time.perf_counter()

            pose_vector_c[3] = pose_vector_c[1]
            pose_vector_c[4] = pose_vector_c[2]

            model_input_arr = eyebrow_vector_c
            model_input_arr.extend(mouth_eye_vector_c)
            model_input_arr.extend(pose_vector_c)

            self.model_process_input_queue.put_nowait(model_input_arr)

            has_model_output = 0
            try:
                new_model_output = model_output
                while not self.model_process_output_queue.empty():
                    has_model_output += 1
                    new_model_output = self.model_process_output_queue.get_nowait()
                model_output = new_model_output
            except queue.Empty:
                pass
            if model_output is None:
                time.sleep(1)
                continue

            # model_output = self.model_process_output_queue.get()

            postprocessed_image = model_output

            # if self.extra_image is not None:
            #     postprocessed_image = cv2.vconcat([postprocessed_image, self.extra_image])

            k_scale = 1
            rotate_angle = 0
            dx = 0
            dy = 0
            if args.extend_movement:
                k_scale = position_vector[2] * math.sqrt(args.extend_movement) + 1
                rotate_angle = -position_vector[0] * 10 * args.extend_movement
                dx = position_vector[0] * 400 * k_scale * args.extend_movement
                dy = -position_vector[1] * 600 * k_scale * args.extend_movement
            if args.bongo:
                rotate_angle -= 5
            rm = cv2.getRotationMatrix2D((IMG_WIDTH / 2, IMG_WIDTH / 2), rotate_angle, k_scale)
            rm[0, 2] += dx + args.output_w / 2 - IMG_WIDTH / 2
            rm[1, 2] += dy + args.output_h / 2 - IMG_WIDTH / 2

            postprocessed_image = cv2.warpAffine(
                postprocessed_image,
                rm,
                (args.output_w, args.output_h))

            if args.anime4k:
                alpha_channel = postprocessed_image[:, :, 3]
                alpha_channel = cv2.resize(alpha_channel, None, fx=2, fy=2)

                # a.load_image_from_numpy(cv2.cvtColor(postprocessed_image, cv2.COLOR_RGBA2RGB), input_type=ac.AC_INPUT_RGB)
                # img = cv2.imread("character/test41.png")
                img1 = cv2.cvtColor(postprocessed_image, cv2.COLOR_RGBA2BGR)
                # a.load_image_from_numpy(img, input_type=ac.AC_INPUT_BGR)
                a.load_image_from_numpy(img1, input_type=ac.AC_INPUT_BGR)
                a.process()
                postprocessed_image = a.save_image_to_numpy()
                postprocessed_image = cv2.merge((postprocessed_image, alpha_channel))
                postprocessed_image = cv2.cvtColor(postprocessed_image, cv2.COLOR_BGRA2RGBA)
            if args.alpha_split:
                alpha_image = cv2.merge(
                    [postprocessed_image[:, :, 3], postprocessed_image[:, :, 3], postprocessed_image[:, :, 3]])
                alpha_image = cv2.cvtColor(alpha_image, cv2.COLOR_RGB2RGBA)
                postprocessed_image = cv2.hconcat([postprocessed_image, alpha_image])

            # if args.output_webcam:
            #     result_image = postprocessed_image
            #     if args.output_webcam == 'obs':
            #         result_image = cv2.cvtColor(result_image, cv2.COLOR_RGBA2RGB)
            #     cam.send(result_image)
            #     cam.sleep_until_next_frame()
            
            if not display_queue.full():
                display_queue.put(postprocessed_image.copy()) 

class FlaskAPI(Resource):
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('type', required=True)
        parser.add_argument('speech_path', default=None)
        parser.add_argument('music_path', default=None)
        parser.add_argument('voice_path', default=None)
        parser.add_argument('mouth_offset', default=0.0)
        parser.add_argument('beat', default=2)
        parser.add_argument('img', default=None)
        json_args = parser.parse_args()

        try:
            global alive
            if json_args['type'] == "speak":
                if json_args['speech_path']:
                    alive.speak(json_args['speech_path'])
                else:
                    return {"status": "Need speech_path!! 0.0", "receive args": json_args}, 200
            elif json_args['type'] == "rhythm":
                if json_args['music_path']:
                    alive.rhythm(json_args['music_path'], int(json_args['beat']))
                else:
                    return {"status": "Need music_path!! 0.0", "receive args": json_args}, 200
            elif json_args['type'] == "sing":
                if json_args['music_path'] and json_args['voice_path']:
                    alive.sing(json_args['music_path'], json_args['voice_path'], float(json_args['mouth_offset']), int(json_args['beat']))
                else:
                    return {"status": "Need music_path and voice_path!! 0.0", "receive args": json_args}, 200
            elif json_args['type'] == "stop":
                global alive_args
                alive_args["is_speech"].value = False
                alive_args["is_singing"].value = False
                alive_args["is_music_play"].value = False
            elif json_args['type'] == "change_img":
                if json_args['img']:
                    global model_process_args
                    input_image, _ = prepare_input_img(512, json_args['img'])
                    model_process_args['input_image_q'].put_nowait(input_image)
                else:
                    return {"status": "Need img!! 0.0", "receive args": json_args}, 200
            else:
                print('No type name {}!! 0.0'.format(json_args['type']))
        except Exception as ex:
            print(ex)

        return {'status': "success"}, 200  # 返回200 OK数据


if __name__ == '__main__':
    print('torch.cuda.is_available() ', torch.cuda.is_available())
    print('torch.cuda.device_count() ', torch.cuda.device_count())
    print('torch.cuda.get_device_name(0) ', torch.cuda.get_device_name(0))
    device = torch.device('cuda:0') if torch.cuda.is_available() else torch.device('cpu')

    input_image, extra_image = prepare_input_img(512, args.character)

    deepseek = DeepSeek()
    deepseek.load_tts_model()

    # 声明跨进程公共参数
    model_process_args = {
        "output_queue": Queue(maxsize=3),
        "input_queue": Queue(),
        "input_image_q": Queue()
    }
    # 初始化动作模块
    model_process = ModelClientProcess(input_image, device, model_process_args)
    model_process.daemon = True
    model_process.start()

    # 声明跨进程公共参数
    alive_args = {
        "is_speech": Value(c_bool, False),
        "speech_q": Queue(),
        "is_singing": Value(c_bool, False),
        "is_music_play": Value(c_bool, False),
        "beat_q": Queue(),
        "mouth_q": Queue(),
    }
    # 初始化模块
    alive = Alive(alive_args)
    alive.start()

    # 初始化主进程
    aiv = EasyAIV(model_process_args, alive_args)
    aiv.start()

    api.add_resource(FlaskAPI, '/alive')
    app.run(port=args.port)  # 运行 Flask app
    print('process done')
