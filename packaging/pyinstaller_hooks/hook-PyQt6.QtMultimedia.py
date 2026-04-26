# 与 PyInstaller 自带 hook 一致：显式放 additional-hooks 中，确保 MERGE / 老版本也能收集
# QtMultimedia 及 Qt6 依赖的 DLL 与数据文件。
# https://github.com/pyinstaller/pyinstaller/blob/develop/PyInstaller/hooks/hook-PyQt6.QtMultimedia.py
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
