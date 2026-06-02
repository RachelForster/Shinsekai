from frontend_bridge_core.tools import _file_browser_root_key, _file_browser_root_label, _strip_windows_verbatim_prefix


def test_strip_windows_verbatim_drive_prefix():
    assert _strip_windows_verbatim_prefix("\\\\?\\D:\\") == "D:\\"
    assert _strip_windows_verbatim_prefix("//?/D:/Games") == "D:/Games"


def test_strip_windows_verbatim_unc_prefix():
    assert _strip_windows_verbatim_prefix(r"\\?\UNC\server\share\asset.png") == r"\\server\share\asset.png"
    assert _strip_windows_verbatim_prefix("//?/UNC/server/share/asset.png") == "//server/share/asset.png"


def test_windows_drive_root_keys_collapse_verbatim_and_normal_paths():
    assert _file_browser_root_key("\\\\?\\D:\\") == _file_browser_root_key("D:/")
    assert _file_browser_root_key("//?/D:/") == _file_browser_root_key("D:/")


def test_windows_drive_root_labels_drop_verbatim_prefixes():
    assert _file_browser_root_label("\\\\?\\D:\\", "D:/") == "D:"
    assert _file_browser_root_label("//?/D:/", "D:/") == "D:"
