"""聊天启动与模板文件读写。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from llm.template_generator import TRANSPARENT_BG
from ui.settings_ui.context import SettingsUIContext
from ui.settings_ui.feedback import is_failure_message
from i18n import tr as tr_i18n

_main_chat_process = None

# 模板文件分节（保存到 .txt）；无标记的旧文件解析为 (全文, "")。
MARK_SCENARIO = "<<<EASYAI_USER_SCENARIO>>>"
MARK_SYSTEM = "<<<EASYAI_SYSTEM_TEMPLATE>>>"
TEMP_SPLIT_META = "_temp_split.json"


def compose_stored_template(scenario: str, system: str) -> str:
    """写入磁盘的带标记格式。"""
    a = (scenario or "").replace("\r\n", "\n").rstrip()
    b = (system or "").replace("\r\n", "\n").rstrip()
    return f"{MARK_SCENARIO}\n{a}\n{MARK_SYSTEM}\n{b}\n"


def parse_stored_template(raw: str) -> tuple[str, str]:
    """读盘：有标记则拆分；否则整段视为用户情景，系统段为空。"""
    text = (raw or "").replace("\r\n", "\n")
    if MARK_SCENARIO in text and MARK_SYSTEM in text:
        try:
            i = text.index(MARK_SCENARIO) + len(MARK_SCENARIO)
            j = text.index(MARK_SYSTEM, i)
            scenario = text[i:j].strip("\n")
            system = text[j + len(MARK_SYSTEM) :].strip("\n")
            return scenario, system
        except ValueError:
            pass
    t = text.strip()
    return (t, "") if t else ("", "")


def compose_for_llm(scenario: str, system: str) -> str:
    """传给主进程的完整 system prompt。"""
    a = (scenario or "").strip()
    b = (system or "").strip()
    if a and b:
        return f"{a}\n\n{b}"
    return a or b


def _history_id_from_scenario(user_scenario: str, system_template: str) -> str:
    """默认聊天记录文件名：由用户情景内容决定哈希；情景为空时用系统段兜底。"""
    stab = (user_scenario or "").strip()
    if stab:
        return hashlib.md5(stab.encode("utf-8")).hexdigest()
    return hashlib.md5((system_template or "").encode("utf-8")).hexdigest()


def _latest_history_json(history_dir: str) -> Path | None:
    d = Path(history_dir)
    if not d.is_dir():
        return None
    files = [p for p in d.glob("*.json") if p.is_file()]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def _read_split_meta(td: Path) -> tuple[str, str] | None:
    meta = td / TEMP_SPLIT_META
    if not meta.is_file():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    sc = data.get("scenario", "")
    sy = data.get("system", "")
    if not isinstance(sc, str):
        sc = ""
    if not isinstance(sy, str):
        sy = ""
    if sc.strip() or sy.strip():
        return sc, sy
    return None


def _resume_scenario_system(ctx: SettingsUIContext) -> tuple[str, str] | None:
    """优先 _temp.txt（与同目录 meta 或分节标记），否则最近修改的其它 .txt。"""
    td = Path(ctx.template_dir_path)
    if not td.is_dir():
        return None
    temp = td / "_temp.txt"
    if temp.is_file() and temp.stat().st_size > 0:
        parts = _read_split_meta(td)
        if parts is not None:
            return parts
        try:
            raw = temp.read_text(encoding="utf-8")
        except OSError:
            raw = ""
        scen, sys = parse_stored_template(raw)
        if (scen or "").strip() or (sys or "").strip():
            return scen, sys

    txts = [p for p in td.glob("*.txt") if p.is_file() and p.name != "_temp.txt"]
    if not txts:
        return None
    path = max(txts, key=lambda p: p.stat().st_mtime)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    scen, sys = parse_stored_template(raw)
    if (scen or "").strip() or (sys or "").strip():
        return scen, sys
    return None


def launch_chat_resume_last(
    ctx: SettingsUIContext,
) -> tuple[bool, str]:
    """
    用最近修改的聊天记录 + 可用模板启动主程序（与「聊天模板」页逻辑一致）。
    返回 (成功, 文案)。
    """
    hp = _latest_history_json(ctx.history_dir)
    if hp is None:
        return False, tr_i18n("api.resume.no_history")
    tpl_parts = _resume_scenario_system(ctx)
    if not tpl_parts:
        return False, tr_i18n("api.resume.no_template")
    scen, sys_t = tpl_parts
    room_id = getattr(ctx.config_manager.config.system_config, "live_room_id", "") or ""
    msg = launch_chat(
        ctx,
        scen,
        sys_t,
        "",
        str(hp.resolve()),
        TRANSPARENT_BG,
        "否",
        str(room_id).strip(),
    )
    if is_failure_message(msg):
        return False, msg
    return True, msg


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
    user_scenario: str,
    system_template: str,
    init_sprite_path: str,
    history_file: str,
    selected_bg: str,
    use_cg: str,
    room_id: str,
) -> str:
    global _main_chat_process
    print("启动聊天，使用模板:")
    try:
        template = compose_for_llm(user_scenario, system_template)

        dest_path = os.path.join(ctx.template_dir_path, "_temp.txt")
        with open(dest_path, mode="+wt", encoding="utf-8") as file:
            file.write(template)

        meta_path = Path(ctx.template_dir_path) / TEMP_SPLIT_META
        try:
            meta_path.write_text(
                json.dumps(
                    {"scenario": user_scenario, "system": system_template},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

        init_path = init_sprite_path or ""
        history_file = history_file if history_file else ""
        ctx.config_manager.config.system_config.live_room_id = room_id
        ctx.config_manager.save_system_config()

        if _main_chat_process is None or _main_chat_process.poll() is not None:
            template_hash = _history_id_from_scenario(user_scenario, system_template)
            history_file_path = Path(history_file) if history_file else Path(f"{ctx.history_dir}/{template_hash}.json")
            t2i = "ComfyUI" if use_cg == "是" else ""
            root = _release_root()
            tts_slug = (
                getattr(ctx.config_manager.config.api_config, "tts_provider", None)
                or "gpt-sovits"
            )
            tts_slug = str(tts_slug).strip() or "gpt-sovits"
            args = [
                "--template=_temp",
                f"--init_sprite_path={init_path}",
                f"--history={history_file_path.resolve()}",
                f"--bg={selected_bg}",
                f"--t2i={t2i}",
                f"--room_id={room_id}",
                f"--tts={tts_slug}",
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


def load_template_from_file(ctx: SettingsUIContext, file_path: str) -> tuple[str, str, str]:
    """返回 (情景, 系统模板, 文件名)。失败时首段为以「加载失败」开头的错误文案。"""
    try:
        file_name = file_path
        full_path = os.path.join(ctx.template_dir_path, file_path)
        with open(full_path, "r", encoding="utf-8") as f:
            raw = f.read()
        s, t = parse_stored_template(raw)
        return s, t, file_name
    except Exception as e:
        return f"加载失败: {str(e)}", "", file_path


def save_template(
    ctx: SettingsUIContext, scenario: str, system: str, filename: str
) -> tuple[str, list[str]]:
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
            file.write(compose_stored_template(scenario, system))
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
    use_choice: str,
    use_narration: str,
    max_speech_chars: int,
    max_dialog_items: int,
) -> tuple[str, str]:
    template, out = ctx.template_generator.generate_chat_template(
        selected_characters,
        bg_name,
        use_effect == "是",
        use_cg == "是",
        use_translation == "是",
        use_cot == "是",
        use_choice == "是",
        use_narration == "是",
        max_speech_chars=max(0, int(max_speech_chars)),
        max_dialog_items=max(0, int(max_dialog_items)),
    )
    return template, out
