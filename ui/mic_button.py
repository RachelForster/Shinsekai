import sys
from PyQt5.QtWidgets import (QPushButton, QTextEdit)
from PyQt5.QtGui import QIcon, QColor, QFont
from PyQt5.QtCore import QSize, Qt, pyqtSignal, QObject

# 导入您提供的适配器文件 (假设文件名为 asr_adapter.py 并在同一目录下)
# 实际项目中，您可能需要确保 asr_adapter.py 中的所有依赖（如 RealtimeSTT, vosk, pyaudio）已安装。
from asr.asr_adapter import VoskAdapter

class ASRSignals(QObject):
    """
    定义 ASR 结果的信号，用于从 ASR 线程安全地更新 UI。
    
    参数: 
        str: 转录文本
        bool: 是否是部分结果 (True) 或最终结果 (False)
    """
    transcription_update = pyqtSignal(str, bool)

# --- 2. MicButton 组件 (控制器) ---
class MicButton(QPushButton):
    """
    一个带有麦克风图标的按钮，用于控制 ASR 服务的开启和关闭。
    """
    ACTIVE_COLOR = "#6377AD"  # ASR 运行时的颜色
    INACTIVE_COLOR = "#E0E0E0"  # ASR 停
    # 定义一个外部可连接的信号，用于通知 ASR 状态变化
    asr_state_changed = pyqtSignal(bool) # True for running, False for stopped
    asr_pause_requested = pyqtSignal()
    asr_resume_requested = pyqtSignal()
    send_final_transcription = pyqtSignal()

    def __init__(self, asr_adapter = None, parent=None):
        super().__init__(parent)
        self.asr_adapter = asr_adapter
        if asr_adapter is None:
            # 默认使用 Vosk 适配器，语言为中文
            self.asr_adapter = VoskAdapter(
                language="zh", callback=self._handle_transcription_update)
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
        
        self._setup_ui()
        self.clicked.connect(self._toggle_asr)

    def _setup_ui(self):
        """配置按钮的样式和图标。"""
        
        # 使用 FontAwesome 的麦克风图标（如果系统支持或已配置 QFont）
        # 实际项目中，更推荐使用 QIcon 加载本地图片文件 (.png, .svg)
        self.setText("🎤") 
        self.setFont(QFont("Arial", 16))
        self.setFixedSize(QSize(50, 50))
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.INACTIVE_COLOR}; /* 默认灰色 */
                border-radius: 25px;
            }}
        """)

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
            print(f"Warning: line_edit not set. Transcription: {text}")
            return

        if is_partial:
            # print(f"Partial transcription: {text}")
            self.line_edit.setText(self.original_text + text)
        else:
            # print(f"Final transcription: {text}")
            text = text.replace(' ', '').strip()
            self.line_edit.setText(self.original_text + ('，' if self.original_text else '') + text)
            self.original_text = self.line_edit.text()
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
            
        print("尝试启动 ASR...")
        try:
            # 记录当前输入框中的文本，作为转录结果的前缀
            if hasattr(self, 'line_edit'):
                 self.original_text = self.line_edit.toPlainText()
            self.setStyleSheet(self.styleSheet().replace(self.INACTIVE_COLOR, self.ACTIVE_COLOR))
            self.asr_adapter.start()
            self._is_asr_running = True
            self.asr_state_changed.emit(True)
            print("ASR 已启动。")
        except Exception as e:
            print(f"ASR 启动失败: {e}")

    def pause_asr(self):
        """暂停 ASR 服务。"""
        if not self._is_asr_running:
            return
        print("尝试暂停 ASR...")
        self.asr_adapter.pause()
    
    def resume_asr(self):
        """恢复 ASR 服务。"""
        if not self._is_asr_running:
            return
        print("尝试恢复 ASR...")
        self.original_text = ''
        self.line_edit.setText(self.original_text)  # 恢复到暂停时的文本
        self.asr_adapter.resume()

    def stop_asr(self):
        """停止 ASR 服务。"""
        if not self._is_asr_running:
            return

        print("尝试停止 ASR...")
        try:
            self.setStyleSheet(self.styleSheet().replace(self.ACTIVE_COLOR, self.INACTIVE_COLOR))
            self.asr_adapter.stop()
            self._is_asr_running = False
            self.asr_state_changed.emit(False)
            print("ASR 已停止。")
        except Exception as e:
            print(f"ASR 停止失败: {e}")

    def is_running(self) -> bool:
        """返回 ASR 服务是否在运行。"""
        return self._is_asr_running
    
    def closeEvent(self, event):
        """确保在关闭时停止 ASR 服务。"""
        if self._is_asr_running:
            self.stop_asr()