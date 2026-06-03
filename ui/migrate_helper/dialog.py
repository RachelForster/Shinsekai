"""Qt dialog for guiding users during the frontend UI migration."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QDialog,
)

from ui.migrate_helper.release import (
    RELEASES_URL,
    current_platform_label,
    resolve_download_target,
)

_ROOT = Path(__file__).resolve().parents[2]


_QSS = """
QDialog#migrationRoleDialog {
    background: #fff7fa;
}
QFrame#migrationHero {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #fff1f6, stop:1 #ffffff);
    border: 1px solid rgba(212, 120, 142, 0.28);
    border-radius: 14px;
}
QLabel#migrationTitle {
    color: #241820;
    font-size: 20px;
    font-weight: 700;
}
QLabel#migrationSubtitle,
QLabel#migrationBody,
QLabel#migrationMuted {
    color: #6b5860;
}
QLabel#migrationSectionTitle {
    color: #2d1b24;
    font-size: 15px;
    font-weight: 650;
}
QPushButton#migrationRoleButton {
    min-height: 72px;
    padding: 12px 14px;
    border: 1px solid rgba(212, 120, 142, 0.25);
    border-radius: 12px;
    color: #4f3642;
    background: #ffffff;
    font-weight: 650;
    text-align: left;
}
QPushButton#migrationRoleButton:hover {
    border-color: rgba(212, 120, 142, 0.52);
    background: #fff3f7;
}
QPushButton#migrationRoleButton:checked {
    border-color: #d4788e;
    color: #9b405b;
    background: #ffe8f0;
}
QFrame#migrationPanel {
    background: #ffffff;
    border: 1px solid rgba(212, 120, 142, 0.18);
    border-radius: 12px;
}
QLabel#migrationCode {
    padding: 8px 10px;
    border: 1px solid rgba(212, 120, 142, 0.22);
    border-radius: 8px;
    color: #432a36;
    background: #fff7fa;
    font-family: Consolas, "Microsoft YaHei UI", monospace;
}
QPushButton {
    min-height: 32px;
    padding: 6px 14px;
    border: 1px solid rgba(212, 120, 142, 0.34);
    border-radius: 8px;
    color: #5f3446;
    background: #ffffff;
}
QPushButton:hover {
    border-color: #d4788e;
    background: #fff0f5;
}
QPushButton:pressed {
    background: #ffe0eb;
}
QPushButton#migrationPrimaryButton {
    border-color: #d4788e;
    color: #ffffff;
    background: #d4788e;
    font-weight: 650;
}
QPushButton#migrationPrimaryButton:hover {
    background: #c7637d;
}
QPushButton:disabled {
    color: #aa97a0;
    background: #f8edf1;
}
"""


class _ReleaseResolverWorker(QThread):
    resolved = Signal(str, str, bool, str)

    def run(self) -> None:
        try:
            target = resolve_download_target()
            self.resolved.emit(target.url, target.label, target.direct, target.message)
        except Exception as exc:  # pragma: no cover - depends on network state
            self.resolved.emit(
                RELEASES_URL,
                "Releases",
                False,
                f"获取最新发行包失败，已打开 Releases 页面：{exc}",
            )


class MigrationRoleDialog(QDialog):
    """Choose the migration path for frontend users."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: _ReleaseResolverWorker | None = None

        self.setObjectName("migrationRoleDialog")
        self.setWindowTitle("Shinsekai Frontend 迁移助手")
        self.setModal(True)
        self.setMinimumWidth(620)
        self.setStyleSheet(_QSS)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(14)

        hero = QFrame(self)
        hero.setObjectName("migrationHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(18, 16, 18, 16)
        hero_layout.setSpacing(7)

        title = QLabel("选择你的 Frontend 迁移方式", hero)
        title.setObjectName("migrationTitle")
        hero_layout.addWidget(title)

        subtitle = QLabel(
            "新设置中心正在从 Qt 迁移到 React Frontend。请选择身份，我会展示对应的下一步。",
            hero,
        )
        subtitle.setObjectName("migrationSubtitle")
        subtitle.setWordWrap(True)
        hero_layout.addWidget(subtitle)
        root.addWidget(hero)

        role_row = QHBoxLayout()
        role_row.setSpacing(10)
        self._developer_btn = self._make_role_button(
            "我是开发者\n配置 pnpm 环境，按 README 运行和验证前端。"
        )
        self._user_btn = self._make_role_button(
            "我是普通用户\n下载当前平台发行包，直接安装或运行。"
        )
        role_row.addWidget(self._developer_btn)
        role_row.addWidget(self._user_btn)
        root.addLayout(role_row)

        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self._developer_btn, 0)
        group.addButton(self._user_btn, 1)
        group.idClicked.connect(self._set_role)

        self._stack = QStackedWidget(self)
        self._stack.addWidget(self._developer_panel())
        self._stack.addWidget(self._user_panel())
        root.addWidget(self._stack)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        close_btn = QPushButton("关闭", self)
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(close_btn)
        root.addLayout(bottom)

        self._user_btn.setChecked(True)
        self._set_role(1)

    def _make_role_button(self, text: str) -> QPushButton:
        button = QPushButton(text, self)
        button.setObjectName("migrationRoleButton")
        button.setCheckable(True)
        return button

    def _developer_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("migrationPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        heading = QLabel("开发者指引", panel)
        heading.setObjectName("migrationSectionTitle")
        layout.addWidget(heading)

        body = QLabel(
            "适合从源码参与 Qt 到 Frontend 的迁移、调试 bridge、开发页面和提交 PR。",
            panel,
        )
        body.setObjectName("migrationBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        steps = QLabel(
            "1. 安装 Node.js 20+，并启用 Corepack。\n"
            "2. 在 frontend 目录安装依赖。\n"
            "3. 按 README 启动 React 设置中心和 Python bridge。",
            panel,
        )
        steps.setObjectName("migrationBody")
        steps.setWordWrap(True)
        layout.addWidget(steps)

        commands = QLabel(
            "corepack enable\n"
            "corepack pnpm --dir frontend install\n"
            "corepack pnpm --dir frontend dev --host 127.0.0.1 --port 5174",
            panel,
        )
        commands.setObjectName("migrationCode")
        commands.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(commands)

        buttons = QHBoxLayout()
        readme_btn = QPushButton("查看 frontend README", panel)
        readme_btn.clicked.connect(lambda: self._open_local_file(_ROOT / "frontend" / "README.md"))
        root_readme_btn = QPushButton("查看项目 README", panel)
        root_readme_btn.clicked.connect(lambda: self._open_local_file(_ROOT / "README.md"))
        frontend_dir_btn = QPushButton("打开 frontend 目录", panel)
        frontend_dir_btn.clicked.connect(lambda: self._open_local_file(_ROOT / "frontend"))
        buttons.addWidget(readme_btn)
        buttons.addWidget(root_readme_btn)
        buttons.addWidget(frontend_dir_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return panel

    def _user_panel(self) -> QWidget:
        panel = QFrame(self)
        panel.setObjectName("migrationPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        heading = QLabel("普通用户指引", panel)
        heading.setObjectName("migrationSectionTitle")
        layout.addWidget(heading)

        body = QLabel(
            "适合只想使用新版 Frontend 设置中心的用户。点击下载后会自动匹配当前平台的最新发行包；"
            "如果没有匹配到安装包，会打开 GitHub Releases 页面手动选择。",
            panel,
        )
        body.setObjectName("migrationBody")
        body.setWordWrap(True)
        layout.addWidget(body)

        platform_label = QLabel(f"当前平台：{current_platform_label()}", panel)
        platform_label.setObjectName("migrationCode")
        platform_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(platform_label)

        self._download_status = QLabel("建议下载 msi / exe / dmg / AppImage 等发行包，而不是源码压缩包。", panel)
        self._download_status.setObjectName("migrationMuted")
        self._download_status.setWordWrap(True)
        layout.addWidget(self._download_status)

        buttons = QHBoxLayout()
        self._download_btn = QPushButton("下载当前平台发行包", panel)
        self._download_btn.setObjectName("migrationPrimaryButton")
        self._download_btn.clicked.connect(self._download_current_platform)
        releases_btn = QPushButton("打开 Releases", panel)
        releases_btn.clicked.connect(lambda: self._open_url(RELEASES_URL))
        buttons.addWidget(self._download_btn)
        buttons.addWidget(releases_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        return panel

    def _set_role(self, role_id: int) -> None:
        self._stack.setCurrentIndex(role_id)

    def _download_current_platform(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._download_btn.setEnabled(False)
        self._download_status.setText("正在查询最新发行包...")
        self._worker = _ReleaseResolverWorker(self)
        self._worker.resolved.connect(self._on_release_resolved)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.finished.connect(lambda: setattr(self, "_worker", None))
        self._worker.start()

    def _on_release_resolved(
        self,
        url: str,
        label: str,
        direct: bool,
        message: str,
    ) -> None:
        self._download_btn.setEnabled(True)
        self._download_status.setText(message)
        self._open_url(url)
        if direct:
            self._download_status.setText(f"{message}\n浏览器已开始打开下载链接。")
        else:
            self._download_status.setText(f"{message}\n请在页面中选择当前平台安装包。")

    def _open_local_file(self, path: Path) -> None:
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
            return
        self._open_url(RELEASES_URL)

    def _open_url(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))


def show_migration_role_dialog(parent: QWidget | None = None) -> int:
    dialog = MigrationRoleDialog(parent)
    return int(dialog.exec())


def main() -> int:
    app = QApplication.instance() or QApplication([])
    dialog = MigrationRoleDialog()
    return int(dialog.exec())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
