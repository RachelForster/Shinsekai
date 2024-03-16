import gradio as gr
import requests
import argparse


def speak(speak_file):
    if speak_file:
        data = {
            "type": "speak",
            "speech_path": speak_file
        }
        res = requests.post(f'http://127.0.0.1:{args.main_port}/alive', json=data)
        print(res.json())


def rhythm(rhythm_file, rhythm_beat):
    if rhythm_file:
        data = {
            "type": "rhythm",
            "music_path": rhythm_file.name,
            "beat": rhythm_beat
        }
        res = requests.post(f'http://127.0.0.1:{args.main_port}/alive', json=data)
        print(res.json())


def sing(sing_file, sing_voice_file, sing_beat, sing_mouth):
    if sing_file and sing_voice_file:
        data = {
            "type": "sing",
            "music_path": sing_file.name,
            "voice_path": sing_voice_file.name,
            "beat": sing_beat,
            "mouth_offset": sing_mouth
        }
        res = requests.post(f'http://127.0.0.1:{args.main_port}/alive', json=data)
        print(res.json())


def stop():
    data = {
        "type": "stop",
    }
    res = requests.post(f'http://127.0.0.1:{args.main_port}/alive', json=data)
    print(res.json())


def change_img(img_path):
    print(img_path)
    if img_path:
        data = {
            "type": "change_img",
            "img": img_path
        }
        res = requests.post(f'http://127.0.0.1:{args.main_port}/alive', json=data)
        print(res.json())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--main_port', type=int, default=7888)
    parser.add_argument('--webui_port', type=int, default=7999)
    args = parser.parse_args()

    support_audio_type = ["audio"]  # ".wav", ".mp3", ".flac"

    with gr.Blocks() as demo:
        with gr.Tab("说话"):
            speak_file = gr.File(label="语音音频", file_types=support_audio_type)
            speak_but = gr.Button("说话！！")
            speak_but.click(speak, [speak_file])
        with gr.Tab("摇"):
            rhythm_file = gr.File(label="音乐音频", file_types=support_audio_type)
            rhythm_beat = gr.Radio(["1", "2", "4"], value="2", label="节奏", info="越小点头频率越快")
            rhythm_but = gr.Button("摇！")
            rhythm_but.click(rhythm, [rhythm_file, rhythm_beat])
        with gr.Tab("唱歌"):
            with gr.Row():
                with gr.Column():
                    sing_file = gr.File(label="原曲音频", file_types=support_audio_type)
                with gr.Column():
                    sing_voice_file = gr.File(label="人声音频", file_types=support_audio_type)
            sing_beat = gr.Radio(["1", "2", "4"], value="2", label="节奏", info="越小点头频率越快")
            sing_mouth = gr.Slider(0, 1, value=0, step=0.1, label="嘴巴大小偏移", info="如果角色唱歌时的嘴张的不够大，可以试试将这个值设大")
            sing_but = gr.Button("唱歌喵")
            sing_but.click(sing, [sing_file, sing_voice_file, sing_beat, sing_mouth])
        with gr.Tab("换皮"):
            img = gr.Image(label="上传图片（512x512）", type="filepath", image_mode="RGBA")  # , height=300, width=300
            change_but = gr.Button("启动！")
            change_but.click(change_img, [img])

        stop_but = gr.Button("停止当前动作")
        stop_but.click(stop)

    demo.launch(server_port=args.webui_port, inbrowser=True)
