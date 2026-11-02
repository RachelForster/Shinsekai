from frontend_bridge_core.path_utils import strip_windows_verbatim_prefix


def test_strip_drops_long_path_prefix():
    assert strip_windows_verbatim_prefix("\\\\?\\D:\\tts_bundles\\gpt") == "D:\\tts_bundles\\gpt"
    assert strip_windows_verbatim_prefix("//?/D:/tts_bundles/gpt") == "D:/tts_bundles/gpt"


def test_strip_keeps_unc_root():
    assert strip_windows_verbatim_prefix(r"\\?\UNC\server\share\tts") == r"\\server\share\tts"
    assert strip_windows_verbatim_prefix("//?/UNC/server/share/tts") == "//server/share/tts"


def test_strip_leaves_plain_path_untouched():
    assert strip_windows_verbatim_prefix("D:/tts_bundles/gpt") == "D:/tts_bundles/gpt"
