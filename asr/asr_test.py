from pathlib import Path
import sys
current_script = Path(__file__).resolve()
project_root = current_script.parent.parent
print("project_root",project_root)
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from asr.asr_adapter import RealtimeSTTAdapter, VoskAdapter
import threading

def asr_callback(text: str, is_partial: bool):
    """用于接收 ASR 识别结果的回调函数，用于实时更新命令行输出。"""
    # 使用 \r 回到行首，实现实时更新效果
    sys.stdout.write(f"\r[识别中] {text}")
    sys.stdout.flush()
    if not is_partial:
        print(f"\n[识别完成] {text}")

def main():
    adapter = VoskAdapter(language="zh", callback=asr_callback)
    adapter.start()

if __name__ == "__main__":
    main()