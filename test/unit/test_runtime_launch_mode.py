import unittest

from core.runtime.launch_mode import should_init_desktop_mixer


class RuntimeLaunchModeTests(unittest.TestCase):
    def test_desktop_native_mode_initializes_mixer(self):
        self.assertTrue(should_init_desktop_mixer(headless=False, stream_endpoint=""))

    def test_stream_runtime_skips_desktop_mixer_init(self):
        self.assertFalse(
            should_init_desktop_mixer(
                headless=False,
                stream_endpoint="ws://127.0.0.1:8788/ws?sessionId=s1&role=producer",
            )
        )

    def test_headless_runtime_skips_desktop_mixer_init(self):
        self.assertFalse(should_init_desktop_mixer(headless=True, stream_endpoint=""))


if __name__ == "__main__":
    unittest.main()
