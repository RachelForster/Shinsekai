import sys
import threading
import time

from PySide6.QtWidgets import QApplication, QPushButton, QTextEdit
from PySide6.QtGui import QIcon, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtCore import QRectF, QSize, Qt, Signal, QObject

# 导入您提供的适配器文件 (假设文件名为 asr_adapter.py 并在同一目录下)
# 实际项目中，您可能需要确保 asr_adapter.py 中的所有依赖（如 RealtimeSTT, vosk, pyaudio）已安装。
from asr.asr_adapter import create_default_asr_adapter, get_asr_log
from i18n import tr
from ui.chat_ui.rounded_chrome_button import parse_chrome_paint
from ui.chat_ui.theme_chrome import ChatChromeTheme, sanitize_chrome_declarations

_log = get_asr_log()


class ASRSignals(QObject):
    """
    定义 ASR 结果的信号，用于从 ASR 线程安全地更新 UI。
    
    参数: 
        str: 转录文本
        bool: 是否是部分结果 (True) 或最终结果 (False)
    """
    transcription_update = Signal(str, bool)

class _AsrLazyInitNotifier(QObject):
    """在后台线程完成 ``create_default_asr_adapter`` 后，通过信号回到主线程。"""

    adapter_ready = Signal(int, object)
    adapter_failed = Signal(int, object)


class _AsrStartNotifier(QObject):
    """在后台线程完成 ``adapter.start()`` 后，通过信号回到主线程。"""

    start_finished = Signal(int, object)
    start_failed = Signal(int, object, object)


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
        # 默认延迟创建：在后台线程执行 create_default_asr_adapter（加载模型），主线程保持可响应。
        self.asr_adapter = asr_adapter
        self._is_asr_running = False

        self.asr_signals = ASRSignals()
        self.asr_signals.transcription_update.connect(self._handle_transcription_update)
        self.asr_pause_requested.connect(self.pause_asr)
        self.asr_resume_requested.connect(self.resume_asr)

        if self.asr_adapter is not None:
            self.asr_adapter.callback = self._signal_callback

        self._lazy_init_notifier = _AsrLazyInitNotifier(self)
        self._lazy_init_notifier.adapter_ready.connect(
            self._on_lazy_adapter_ready,
            Qt.ConnectionType.QueuedConnection,
        )
        self._lazy_init_notifier.adapter_failed.connect(
            self._on_lazy_adapter_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._lazy_init_running = False
        self._lazy_init_generation = 0
        self._lazy_init_cancel_requested = False
        self._mic_closed = False

        self._start_notifier = _AsrStartNotifier(self)
        self._start_notifier.start_finished.connect(
            self._on_asr_start_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._start_notifier.start_failed.connect(
            self._on_asr_start_failed,
            Qt.ConnectionType.QueuedConnection,
        )
        self._start_generation = 0
        self._start_worker_busy = False
        self._start_cancel_requested = False

        self._window_scale = 1.0
        self._mic_palette_active = self.ACTIVE_COLOR
        self._mic_palette_inactive = self.INACTIVE_COLOR
        self._mic_extra_qss = ""
        self._paint_fill = self.INACTIVE_COLOR
        self._paint_text = "#333333"
        self._paint_bw = 0
        self._paint_bc: str | None = None
        self._paint_r = 20.0
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAutoDefault(False)
        self.setDefault(False)
        self._setup_ui()
        self.clicked.connect(self._toggle_asr)

    def _signal_callback(self, text: str, is_partial: bool) -> None:
        self.asr_signals.transcription_update.emit(text, is_partial)

    def _spawn_lazy_init_thread(self) -> None:
        self._lazy_init_generation += 1
        gen = self._lazy_init_generation
        notifier = self._lazy_init_notifier
        cb = self._signal_callback

        def _run() -> None:
            try:
                adapter = create_default_asr_adapter(cb)
                notifier.adapter_ready.emit(gen, adapter)
            except BaseException as e:
                notifier.adapter_failed.emit(gen, e)

        threading.Thread(
            target=_run, daemon=True, name="easyai_asr_lazy_init"
        ).start()

    def _on_lazy_adapter_ready(self, gen: int, adapter) -> None:
        self._lazy_init_running = False
        if gen != self._lazy_init_generation:
            try:
                adapter.stop()
            except Exception:
                _log.debug("mic: drop stale lazy adapter (generation)", exc_info=True)
            return
        if self._mic_closed or self._lazy_init_cancel_requested:
            try:
                adapter.stop()
            except Exception:
                _log.debug("mic: discard lazy adapter after cancel/close", exc_info=True)
            return
        self.asr_adapter = adapter
        self.start_asr()

    def _on_lazy_adapter_failed(self, gen: int, exc: BaseException) -> None:
        if gen != self._lazy_init_generation:
            return
        self._lazy_init_running = False
        _log.error(
            "mic: background ASR init failed: %s",
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        self._mic_busy_hide()

    def _mic_busy_show(self, text: str, duration_seconds: float = 0.0) -> None:
        """经 ChatUIContext 显示底料加载条（无 context 时忽略）；刷新事件循环以便随后同步加载时条能画出。"""
        try:
            from sdk.chat_ui_context import try_get_chat_ui_context

            ctx = try_get_chat_ui_context()
            if ctx is not None:
                ctx.set_busy_bar(text, duration_seconds)
        except Exception:
            pass
        QApplication.processEvents()

    def _mic_busy_hide(self) -> None:
        try:
            from sdk.chat_ui_context import try_get_chat_ui_context

            ctx = try_get_chat_ui_context()
            if ctx is not None:
                ctx.hide_busy_bar()
        except Exception:
            pass

    def _apply_mic_stylesheet(self, bg: str) -> None:
        """主题与底色改由 paintEvent 绘制圆角，不依赖 QSS。"""
        san = sanitize_chrome_declarations(self._mic_extra_qss)
        parts = parse_chrome_paint(san)
        self._paint_fill = parts.background or bg
        self._paint_text = parts.text_color or "#333333"
        self._paint_bw = parts.border_width
        self._paint_bc = parts.border_color
        side = max(1, int(self.width()))
        max_r = side / 2.0
        if parts.corner_radius_px is not None:
            self._paint_r = min(float(parts.corner_radius_px), max_r)
        else:
            self._paint_r = max(8.0, max_r)
        self.setStyleSheet("")
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bw = self._paint_bw
        inset = max(0, bw)
        rect = QRectF(inset, inset, w - 2 * inset, h - 2 * inset)
        if rect.width() < 1 or rect.height() < 1:
            rect = QRectF(0, 0, float(w), float(h))
        r = min(self._paint_r, rect.width() / 2.0, rect.height() / 2.0)
        path = QPainterPath()
        path.addRoundedRect(rect, r, r)
        fill = QColor(self._paint_fill)
        if not fill.isValid():
            fill = QColor(self.INACTIVE_COLOR)
        if self.isDown():
            fill = fill.darker(115)
        elif self.underMouse():
            fill = fill.lighter(105)
        p.fillPath(path, fill)
        if bw > 0 and self._paint_bc:
            pen = QPen(QColor(self._paint_bc), float(bw))
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.setPen(QColor(self._paint_text))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())

    def apply_window_scale(
        self, scale: float, chrome: ChatChromeTheme | None = None
    ) -> None:
        """随主窗口缩放更新麦克风按钮；``chrome`` 非空时更新主题色与 extra QSS。"""
        self._window_scale = max(0.55, min(2.2, scale))
        if chrome is not None:
            self._mic_palette_active = (
                chrome.mic_active_background or self.ACTIVE_COLOR
            )
            self._mic_palette_inactive = (
                chrome.mic_inactive_background or self.INACTIVE_COLOR
            )
            self._mic_extra_qss = chrome.mic_extra_qss or ""
        side = max(36, int(50 * self._window_scale))
        px = max(11, int(16 * self._window_scale))
        self.setFixedSize(QSize(side, side))
        self.setFont(QFont("Arial", px))
        bg = (
            self._mic_palette_active
            if self._is_asr_running
            else self._mic_palette_inactive
        )
        self._apply_mic_stylesheet(bg)

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
            lang = (getattr(self.asr_adapter, "language", None) or "").strip().lower()
            if lang.startswith("en"):
                text = (text or "").strip()
                sep = " "
            else:
                # CJK：去掉模型插入的多余空格（英文词之间不应受此处理）
                text = (text or "").replace(" ", "").strip()
                sep = "，"
            built = self.original_text + (sep if self.original_text else "") + text
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
        if self._start_worker_busy:
            self._start_generation += 1
            self._start_cancel_requested = True
            self._mic_busy_hide()
            return
        if self._lazy_init_running:
            self._lazy_init_generation += 1
            self._lazy_init_cancel_requested = True
            self._lazy_init_running = False
            self._mic_busy_hide()
            return
        if self._is_asr_running:
            self.stop_asr()
            return
        self._lazy_init_cancel_requested = False
        if self.asr_adapter is None:
            self._mic_busy_show(tr("desktop.mic_loading_model"), 0.0)
            self._lazy_init_running = True
            self._spawn_lazy_init_thread()
            return
        self.start_asr()

    def start_asr(self):
        """启动 ASR（在 ``adapter.start()`` 的工作线程里执行，避免阻塞 Qt 主线程）。"""
        if self._is_asr_running:
            return
        if self.asr_adapter is None:
            _log.warning("mic start_asr: no adapter (still loading or inject one)")
            return
        if self._start_worker_busy:
            return

        if hasattr(self, "line_edit"):
            self.original_text = self.line_edit.toPlainText()

        self._mic_busy_show(tr("desktop.mic_loading_model"), 0.0)
        self._start_worker_busy = True
        self._start_generation += 1
        gen = self._start_generation
        self._start_cancel_requested = False
        ad = self.asr_adapter
        notifier = self._start_notifier
        ad_name = type(ad).__name__
        _log.info("mic start_asr (worker) adapter=%s", ad_name)

        def _run() -> None:
            try:
                ad.start()
                notifier.start_finished.emit(gen, ad)
            except BaseException as e:
                notifier.start_failed.emit(gen, ad, e)

        threading.Thread(
            target=_run, daemon=True, name="easyai_asr_start"
        ).start()

    def _on_asr_start_finished(self, gen: int, ad) -> None:
        self._start_worker_busy = False
        if gen != self._start_generation:
            try:
                ad.stop()
            except Exception:
                _log.debug("mic: stale start_done stop()", exc_info=True)
            return

        if self._mic_closed:
            try:
                ad.stop()
            except Exception:
                pass
            self._mic_busy_hide()
            return
        if self._start_cancel_requested:
            self._start_cancel_requested = False
            try:
                ad.stop()
            except Exception:
                pass
            self._mic_busy_hide()
            return

        try:
            self._apply_mic_stylesheet(self._mic_palette_active)
            self._is_asr_running = True
            self.asr_state_changed.emit(True)
            _log.info("mic start_asr ok adapter=%s", type(self.asr_adapter).__name__)
        finally:
            self._mic_busy_hide()

    def _on_asr_start_failed(self, gen: int, ad, exc: BaseException) -> None:
        self._start_worker_busy = False
        if gen != self._start_generation:
            try:
                ad.stop()
            except Exception:
                pass
            return
        _log.error(
            "mic start_asr failed: %s",
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        try:
            self._apply_mic_stylesheet(self._mic_palette_inactive)
        except Exception:
            self.apply_window_scale(self._window_scale)
        try:
            ad.stop()
        except Exception:
            pass
        self._mic_busy_hide()

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
            self._apply_mic_stylesheet(self._mic_palette_inactive)
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
        self._mic_closed = True
        self._lazy_init_cancel_requested = True
        self._lazy_init_generation += 1
        self._lazy_init_running = False
        self._start_generation += 1
        self._start_cancel_requested = True
        self._start_worker_busy = False
        try:
            if self.asr_adapter is None:
                pass
            elif self._is_asr_running:
                self.stop_asr()
            else:
                self.asr_adapter.stop()
        except Exception:
            _log.exception("mic closeEvent cleanup")
        finally:
            super().closeEvent(event)