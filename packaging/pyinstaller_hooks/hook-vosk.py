# vosk: libvosk.dll 等需落在与 vosk 包同级的真实目录，否则 open_dll 中 add_dll_directory 会报 WinError 2
try:
    from PyInstaller.utils.hooks import collect_all

    datas, binaries, hiddenimports = collect_all("vosk")
except ImportError:
    from PyInstaller.utils.hooks import (
        collect_data_files,
        collect_dynamic_libs,
        collect_submodules,
    )

    datas = collect_data_files("vosk")
    binaries = collect_dynamic_libs("vosk")
    hiddenimports = list(collect_submodules("vosk"))
