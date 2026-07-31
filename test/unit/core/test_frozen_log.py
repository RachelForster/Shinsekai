from core.bootstrap.frozen_log import _frozen_log_filename
from core.paths import safe_path_component


def test_frozen_log_filename_fits_suffix_and_avoids_device_aliases():
    assert _frozen_log_filename("CON") == "app-CON.log"

    filename = _frozen_log_filename("界" * 100)

    assert filename.endswith(".log")
    assert len(filename.encode("utf-8")) <= 255
    assert safe_path_component(filename) == filename
