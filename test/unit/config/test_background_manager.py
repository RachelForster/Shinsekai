from types import SimpleNamespace

from config.background_manager import BackgroundManager
from config.schema import Background


class FakeConfigManager:
    def __init__(self, backgrounds):
        self.config = SimpleNamespace(background_list=backgrounds)
        self.save_count = 0

    def get_background_by_name(self, name):
        return next((background for background in self.config.background_list if background.name == name), None)

    def save_background_config(self):
        self.save_count += 1


def build_manager(backgrounds):
    manager = BackgroundManager.__new__(BackgroundManager)
    manager._config_manager = FakeConfigManager(backgrounds)
    return manager


def test_add_background_updates_existing_tags():
    background = Background(name="School", sprite_prefix="school", bg_tags="Scene 1: old\n", bgm_tags="Music 1: old\n")
    manager = build_manager([background])

    manager.add_background(
        "School",
        "school",
        edit_as_name="School",
        bg_tags="Scene 1: classroom\n",
        bgm_tags="Music 1: calm\n",
    )

    assert background.bg_tags == "Scene 1: classroom\n"
    assert background.bgm_tags == "Music 1: calm\n"
    assert manager._config_manager.save_count == 1


def test_add_background_creates_when_edit_target_is_missing():
    manager = build_manager([])

    manager.add_background(
        "City",
        "city",
        edit_as_name="Missing",
        bg_tags="Scene 1: street\n",
        bgm_tags="Music 1: traffic\n",
    )

    assert len(manager._config_manager.config.background_list) == 1
    assert manager._config_manager.config.background_list[0].name == "City"
    assert manager._config_manager.config.background_list[0].bg_tags == "Scene 1: street\n"
    assert manager._config_manager.config.background_list[0].bgm_tags == "Music 1: traffic\n"
    assert manager._config_manager.save_count == 1
