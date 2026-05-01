from pathlib import Path
import sys

current_script = Path(__file__).resolve()
project_root = current_script.parent.parent
print("project_root", project_root)
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from config.config_manager import ConfigManager
from core.plugins.plugin_host import ensure_plugins_loaded

ensure_plugins_loaded(ConfigManager())

from asr.asr_adapter import create_default_asr_adapter


def asr_callback(text: str, is_partial: bool):
    """用于接收 ASR 识别结果的回调函数，用于实时更新命令行输出。"""
    sys.stdout.write(f"\r[识别中] {text}")
    sys.stdout.flush()
    if not is_partial:
        print(f"\n[识别完成] {text}")


def main():
    adapter = create_default_asr_adapter(asr_callback)
    adapter.start()
    try:
        input("按回车停止…\n")
    finally:
        adapter.stop()


if __name__ == "__main__":
    main()
