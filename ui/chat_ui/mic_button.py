import sys
import time

from PySide6.QtWidgets import QPushButton, QTextEdit
from PySide6.QtGui import QIcon, QColor, QFont
from PySide6.QtCore import QSize, Qt, Signal, QObject

# 导入您提供的适配器文件 (假设文件名为 asr_adapter.py 并在同一目录下)
# 实际项目中，您可能需要确保 asr_adapter.py 中的所有依赖（如 RealtimeSTT, vosk, pyaudio）已安装。
from asr.asr_adapter import create_default_asr_adapter, get_asr_log

_log = get_asr_log()


class ASRSignals(QObject):
    """
    定义 ASR 结果的信号，用于从 ASR 线程安全地更新 UI。
    
    参数: 
        str: 转录文本
        bool: 是否是部分结果 (True) 或最终结果 (False)
    """
    transcription_update = Signal(str, bool)

# --- 2. MicButton 组件 (控制器) ---
class MicButton(QPushButton):
    """
    一个带有麦克风图标的按钮，用于控制 ASR 服务的开启和关闭。
    """
    ACTIVE_COLOR = "#6377AD"  # ASR 运行时的颜色
    INACTIVE_COLOR = "#E0E0E0"  # ASR 停
    # 定义一个外部可连接的信号，用于通知 ASR 状态变化
    asr_state_changed = Signal(bool)  # True for running, False for stopped
    asr_pause_requested = Signal()
    asr_resume_requested = Signal()
    send_final_transcription = Signal()

    def __init__(self, asr_adapter = None, parent=None):
        super().__init__(parent)
        self.asr_adapter = asr_adapter
        if asr_adapter is None:
            self.asr_adapter = create_default_asr_adapter(lambda _t, _p: None)
        self._is_asr_running = False
        
        # 创建信号对象并将其连接到内部回调函数
        self.asr_signals = ASRSignals()
        self.asr_signals.transcription_update.connect(self._handle_transcription_update)
        self.asr_pause_requested.connect(self.pause_asr)
        self.asr_resume_requested.connect(self.resume_asr)

        # 重新配置 ASR 适配器的回调，使其通过信号发送结果到 UI 线程
        def signal_callback(text: str, is_partial: bool):
            self.asr_signals.transcription_update.emit(text, is_partial)

        self.asr_adapter.callback = signal_callback
        
        self._window_scale = 1.0
        self._setup_ui()
        self.clicked.connect(self._toggle_asr)

    def apply_window_scale(self, scale: float) -> None:
        """随主窗口缩放更新麦克风按钮尺寸与字号。"""
        self._window_scale = max(0.55, min(2.2, scale))
        side = max(36, int(50 * self._window_scale))
        r = max(8, side // 2)
        px = max(11, int(16 * self._window_scale))
        self.setFixedSize(QSize(side, side))
        self.setFont(QFont("Arial", px))
        bg = self.ACTIVE_COLOR if self._is_asr_running else self.INACTIVE_COLOR
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: {bg};
                border-radius: {r}px;
            }}
            """
        )

    def _setup_ui(self):
        """配置按钮的样式和图标。"""
        self.setText("🎤")
        self.apply_window_scale(1.0)

    def set_input_widget(self, input: QTextEdit):
        """设置接收转录结果的 QTextEdit 控件。"""
        self.line_edit = input
        # 初始时确保有一个 line_edit 属性，即使为空
        self.original_text = ""

    def _handle_transcription_update(self, text: str, is_partial: bool):
        """
        处理 ASR 线程发出的转录结果，并更新 UI。
        """
        if not hasattr(self, 'line_edit'):
            _log.warning("mic: line_edit not set, drop transcription: %s", text[:120])
            return

        if is_partial:
            # print(f"Partial transcription: {text}")
            self.line_edit.setText(self.original_text + text)
        else:
            # print(f"Final transcription: {text}")
            text = text.replace(" ", "").strip()
            built = self.original_text + ("，" if self.original_text else "") + text
            cur = self.line_edit.toPlainText().strip()
            # RealtimeSTT 等：final 常等于已刷新的整句，避免重复拼接
            if cur and text and (cur == built.strip() or cur.endswith(text)):
                self.original_text = self.line_edit.toPlainText()
            else:
                self.line_edit.setText(built)
                self.original_text = self.line_edit.toPlainText()
            self.send_final_transcription.emit()

    def _toggle_asr(self):
        """切换 ASR 服务的运行状态。"""
        if self._is_asr_running:
            self.stop_asr()
        else:
            self.start_asr()

    def start_asr(self):
        """启动 ASR 服务。"""
        if self._is_asr_running:
            return
            
        ad_name = type(self.asr_adapter).__name__
        _log.info("mic start_asr adapter=%s", ad_name)
        try:
            # 记录当前输入框中的文本，作为转录结果的前缀
            if hasattr(self, 'line_edit'):
                 self.original_text = self.line_edit.toPlainText()
            self.setStyleSheet(self.styleSheet().replace(self.INACTIVE_COLOR, self.ACTIVE_COLOR))
            self.asr_adapter.start()
            self._is_asr_running = True
            self.asr_state_changed.emit(True)
            _log.info("mic start_asr ok adapter=%s", ad_name)
        except Exception:
            _log.exception("mic start_asr failed adapter=%s", ad_name)

    def pause_asr(self):
        """暂停 ASR 服务。"""
        if not self._is_asr_running:
            _log.debug("mic pause_asr: not running, skip")
            return
        _log.info("mic pause_asr adapter=%s", type(self.asr_adapter).__name__)
        self.asr_adapter.pause()
    
    def resume_asr(self):
        """恢复 ASR 服务。"""
        if not self._is_asr_running:
            _log.warning(
                "mic resume_asr: skipped (_is_asr_running=False); "
                "mic may still look on — toggle mic off/on"
            )
            return
        _log.info("mic resume_asr adapter=%s", type(self.asr_adapter).__name__)
        time.sleep(0.5)  # 等待 ASR 适配器完全暂停
        self.original_text = ''
        self.line_edit.setText(self.original_text)  # 恢复到暂停时的文本
        self.asr_adapter.resume()
        _log.info("mic resume_asr done")

    def stop_asr(self):
        """停止 ASR 服务。"""
        if not self._is_asr_running:
            return

        _log.info("mic stop_asr adapter=%s", type(self.asr_adapter).__name__)
        try:
            self.setStyleSheet(self.styleSheet().replace(self.ACTIVE_COLOR, self.INACTIVE_COLOR))
            self.asr_adapter.stop()
            self._is_asr_running = False
            self.asr_state_changed.emit(False)
            _log.info("mic stop_asr ok")
        except Exception:
            _log.exception("mic stop_asr failed")

    def is_running(self) -> bool:
        """返回 ASR 服务是否在运行。"""
        return self._is_asr_running
    
    def closeEvent(self, event):
        """关闭控件时释放 ASR（RealtimeSTT 子进程须 shutdown，否则会刷 BrokenPipe）。"""
        try:
            if self._is_asr_running:
                self.stop_asr()
            else:
                self.asr_adapter.stop()
        except Exception:
            _log.exception("mic closeEvent cleanup")
        finally:
            super().closeEvent(event)