import torch
import cv2
import pyvirtualcam
import numpy as np
from PIL import Image

import tha2.poser.modes.mode_20_wx
from models import TalkingAnime3
from utils import preprocessing_image
from action_animeV2 import ActionAnimeV2
from alive import Alive
from multiprocessing import Value, Process, Queue
from ctypes import c_bool
import asyncio

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

app = Flask(__name__)
api = Api(app)


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

        self.input_image_q = Queue()

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


class EasyAIV(Process):  #
    def __init__(self, extra_image, model_process_args, alive_args):
        super().__init__()
        self.extra_image = extra_image

        self.model_process_input_queue = model_process_args['input_queue']
        self.model_process_output_queue = model_process_args['output_queue']

        self.alive_args_is_speech = alive_args['is_speech']
        self.alive_args_speech_q = alive_args['speech_q']

        self.alive_args_is_singing = alive_args['is_singing']
        self.alive_args_is_music_play = alive_args['is_music_play']
        self.alive_args_beat_q = alive_args['beat_q']
        self.alive_args_mouth_q = alive_args['mouth_q']

    @torch.no_grad()
    def run(self):
        IMG_WIDTH = 512

        cam = None
        if args.output_webcam:
            cam_scale = 1
            cam_width_scale = 1
            if args.anime4k:
                cam_scale = 2
            if args.alpha_split:
                cam_width_scale = 2
            cam = pyvirtualcam.Camera(width=args.output_w * cam_scale * cam_width_scale, height=args.output_h * cam_scale,
                                      fps=30,
                                      backend=args.output_webcam,
                                      fmt=
                                      {'unitycapture': pyvirtualcam.PixelFormat.RGBA, 'obs': pyvirtualcam.PixelFormat.RGB}[
                                          args.output_webcam])
            print(f'Using virtual camera: {cam.device}')

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

            if self.extra_image is not None:
                postprocessed_image = cv2.vconcat([postprocessed_image, self.extra_image])

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

            if args.output_webcam:
                result_image = postprocessed_image
                if args.output_webcam == 'obs':
                    result_image = cv2.cvtColor(result_image, cv2.COLOR_RGBA2RGB)
                cam.send(result_image)
                cam.sleep_until_next_frame()


class FlaskAPI(Resource):
    def post(self):
        parser = reqparse.RequestParser()
        parser.add_argument('type', required=True)
        parser.add_argument('speech_path', default=None)
        parser.add_argument('music_path', default=None)
        parser.add_argument('voice_path', default=None)
        parser.add_argument('mouth_offset', default=0.0)
        parser.add_argument('beat', default=2)
        json_args = parser.parse_args()

        try:
            global alive
            if json_args['type'] == "speak":
                if json_args['speech_path']:
                    alive.speak(json_args['speech_path'])
                else:
                    print('Need speech_path!! 0.0')
                    return {"status": "Need speech_path!! 0.0", "receive args": json_args}, 200
            elif json_args['type'] == "rhythm":
                if json_args['music_path']:
                    alive.rhythm(json_args['music_path'], int(json_args['beat']))
                else:
                    print('Need music_path!! 0.0')
                    return {"status": "Need music_path!! 0.0", "receive args": json_args}, 200
            elif json_args['type'] == "sing":
                if json_args['music_path'] and json_args['voice_path']:
                    alive.sing(json_args['music_path'], json_args['voice_path'], float(json_args['mouth_offset']), int(json_args['beat']))
                else:
                    print('Need music_path and voice_path!! 0.0')
                    return {"status": "Need music_path and voice_path!! 0.0", "receive args": json_args}, 200
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

    # 声明跨进程公共参数
    model_process_args = {
        "output_queue": Queue(maxsize=3),
        "input_queue": Queue(),
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
    aiv = EasyAIV(extra_image, model_process_args, alive_args)
    aiv.start()

    api.add_resource(FlaskAPI, '/alive')
    app.run(port=args.port)  # 运行 Flask app
    print('process done')
