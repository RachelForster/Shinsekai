"""聊天启动与模板文件读写。"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

from ui.settings_ui.context import SettingsUIContext

_main_chat_process = None


def _release_root() -> Path:
    """
    项目根 / 发布根：开发时为仓库根；打包并运行设置界面时为 dist 下与 SettingsUI、main_sprite 同级的发行根
   （见 build_exe/build_settings_exe.py 的目录结构）。
    """
    if os.environ.get("EASYAI_PROJECT_ROOT"):
        return Path(os.environ["EASYAI_PROJECT_ROOT"])
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parent.parent.parent


def launch_chat(
    ctx: SettingsUIContext,
    template: str,
    voice_mode: str,
    init_sprite_path: str,
    history_file: str,
    selected_bg: str,
    use_cg: str,
    room_id: str,
) -> str:
    global _main_chat_process
    print("启动聊天，使用模板:")
    try:
        dest_path = os.path.join(ctx.template_dir_path, "_temp.txt")
        with open(dest_path, mode="+wt", encoding="utf-8") as file:
            file.write(template)

        voice_mode = "gen" if voice_mode == "全语音模式" else "preset"
        init_path = init_sprite_path or ""
        history_file = history_file if history_file else ""
        ctx.config_manager.config.system_config.live_room_id = room_id
        ctx.config_manager.save_system_config()

        if _main_chat_process is None or _main_chat_process.poll() is not None:
            template_hash = hashlib.md5(template.encode("utf-8")).hexdigest()
            history_file_path = Path(history_file) if history_file else Path(f"{ctx.history_dir}/{template_hash}.json")
            t2i = "ComfyUI" if use_cg == "是" else ""
            root = _release_root()
            args = [
                "--template=_temp",
                f"--voice_mode={voice_mode}",
                f"--init_sprite_path={init_path}",
                f"--history={history_file_path.resolve()}",
                f"--bg={selected_bg}",
                f"--t2i={t2i}",
                f"--room_id={room_id}",
            ]
            if getattr(sys, "frozen", False):
                ms = root / "main_sprite" / "main_sprite.exe"
                flat = root / "main_sprite.exe"
                if ms.is_file():
                    _main_chat_process = subprocess.Popen(
                        [str(ms)] + args, cwd=str(root)
                    )
                elif flat.is_file():
                    _main_chat_process = subprocess.Popen(
                        [str(flat)] + args, cwd=str(root)
                    )
                else:
                    return (
                        "启动失败: 未找到 main_sprite.exe（"
                        f"已检查 {ms} 与 {flat}）。请按 packaging 脚本的发行目录结构部署。"
                    )
            else:
                _main_chat_process = subprocess.Popen(
                    [sys.executable, str(root / "main_sprite.py")] + args,
                    cwd=str(root),
                )
            return "聊天进程已启动！PID: " + str(_main_chat_process.pid)
        return "进程已经在运行中！PID: " + str(_main_chat_process.pid)
    except Exception as e:
        print("启动模版失败：", e)
        return f"启动失败: {e}"


def stop_chat() -> str:
    global _main_chat_process
    if _main_chat_process is not None and _main_chat_process.poll() is None:
        _main_chat_process.terminate()
        _main_chat_process.wait()
        pid = _main_chat_process.pid
        _main_chat_process = None
        return f"进程 {pid} 已停止！"
    return "没有正在运行的进程！"


def load_template_from_file(ctx: SettingsUIContext, file_path: str) -> tuple[str, str]:
    try:
        file_name = file_path
        full_path = os.path.join(ctx.template_dir_path, file_path)
        with open(full_path, "r", encoding="utf-8") as f:
            template = f.read()
        return template, file_name
    except Exception as e:
        return f"加载失败: {str(e)}", file_path


def save_template(ctx: SettingsUIContext, template: str, filename: str) -> tuple[str, list[str]]:
    path_obj = Path(ctx.template_dir_path)
    template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
    if filename == "":
        return "保存文件名不能为空！", template_files
    try:
        if filename.endswith(".txt"):
            dest_path = os.path.join(ctx.template_dir_path, filename)
        else:
            dest_path = os.path.join(ctx.template_dir_path, f"{filename}.txt")
        with open(dest_path, mode="+wt", encoding="utf-8") as file:
            file.write(template)
        path_obj = Path(ctx.template_dir_path)
        template_files = [file.name for file in path_obj.iterdir() if file.is_file()]
        return "保存成功", template_files
    except Exception as e:
        return f"保存失败，{e}", template_files


def generate_template(
    ctx: SettingsUIContext,
    selected_characters: list,
    bg_name: str,
    use_effect: str,
    use_translation: str,
    use_cg: str,
    use_cot: str,
) -> tuple[str, str]:
    template, out = ctx.template_generator.generate_chat_template(
        selected_characters,
        bg_name,
        use_effect == "是",
        use_cg == "是",
        use_translation == "是",
        use_cot == "是",
    )
    return template, out
