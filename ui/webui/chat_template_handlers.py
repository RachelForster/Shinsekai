"""聊天启动与模板文件读写（原 webui.py 中的进程与模板逻辑）。"""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

from ui.webui.context import WebUIContext

_main_chat_process = None


def _reject_control_chars(value: str, field: str) -> str:
    text = str(value or "").strip()
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError(f"{field} 包含非法控制字符")
    return text


def _safe_template_filename(filename: str) -> str:
    name = _reject_control_chars(filename, "模板文件名")
    if not name:
        raise ValueError("模板文件名不能为空")
    if not name.endswith(".txt"):
        name = f"{name}.txt"
    if Path(name).name != name or name in {".", ".."}:
        raise ValueError("模板文件名不能包含目录")
    return name


def _template_file(ctx: WebUIContext, filename: str) -> Path:
    root = Path(ctx.template_dir_path).resolve()
    path = (root / _safe_template_filename(filename)).resolve()
    if root not in path.parents and path != root:
        raise PermissionError("模板路径越界")
    return path


def launch_chat(
    ctx: WebUIContext,
    template: str,
    init_sprite_path,
    history_file: str,
    selected_bg: str,
    use_cg: str,
    room_id: str,
) -> str:
    global _main_chat_process
    print("启动聊天，使用模板:")
    try:
        dest_path = _template_file(ctx, "_temp.txt")
        with dest_path.open(mode="+wt", encoding="utf-8") as file:
            file.write(template)

        init_path = _reject_control_chars(init_sprite_path[0], "初始立绘路径") if init_sprite_path else ""
        history_file = _reject_control_chars(history_file, "历史文件路径") if history_file else ""
        ctx.config_manager.config.system_config.live_room_id = room_id
        ctx.config_manager.save_system_config()

        if _main_chat_process is None or _main_chat_process.poll() is not None:
            template_hash = hashlib.md5(template.encode("utf-8")).hexdigest()
            history_file_path = Path(history_file) if history_file else Path(f"{ctx.history_dir}/{template_hash}.json")
            t2i = "ComfyUI" if use_cg == "是" else ""
            python_path = sys.executable
            _main_chat_process = subprocess.Popen(
                [
                    python_path,
                    "main.py",
                    "--template=_temp",
                    f"--init_sprite_path={init_path}",
                    f"--history={history_file_path.resolve()}",
                    f"--bg={selected_bg}",
                    f"--t2i={t2i}",
                    f"--room_id={room_id}",
                ]
            )
            return "聊天进程已启动！PID: " + str(_main_chat_process.pid)
        return "进程已经在运行中！PID: " + str(_main_chat_process.pid)
    except Exception as e:
        print("启动模版失败：", e)


def stop_chat() -> str:
    global _main_chat_process
    if _main_chat_process is not None and _main_chat_process.poll() is None:
        _main_chat_process.terminate()
        _main_chat_process.wait()
        pid = _main_chat_process.pid
        _main_chat_process = None
        return f"进程 {pid} 已停止！"
    return "没有正在运行的进程！"


def load_template_from_file(ctx: WebUIContext, file_path: str):
    try:
        file_name = _safe_template_filename(file_path)
        full_path = _template_file(ctx, file_name)
        with full_path.open("r", encoding="utf-8") as f:
            template = f.read()
        return template, file_name
    except Exception as e:
        return f"加载失败: {str(e)}", file_path


def save_template(ctx: WebUIContext, template: str, filename: str):
    path_obj = Path(ctx.template_dir_path)
    template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
    if filename == "":
        return "保存文件名不能为空！", template_files
    try:
        dest_path = _template_file(ctx, filename)
        with dest_path.open(mode="+wt", encoding="utf-8") as file:
            file.write(template)
        path_obj = Path(ctx.template_dir_path)
        template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
        return "保存成功", template_files
    except Exception as e:
        return f"保存失败，{e}", template_files


def generate_template(
    ctx: WebUIContext,
    selected_characters,
    bg_name: str,
    use_effect: str,
    use_translation: str,
    use_cg: str,
    use_cot: str,
):
    template, out = ctx.template_generator.generate_chat_template(
        selected_characters,
        bg_name,
        use_effect == "是",
        use_cg == "是",
        use_translation == "是",
        use_cot == "是",
        use_choice=True,
        use_narration=True,
        max_speech_chars=0,
        max_dialog_items=0,
    )
    return template, out
