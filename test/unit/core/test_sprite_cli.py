import json
import os
import unittest
from unittest.mock import patch

from core.sprite.sprite_cli import (
    CHAT_LAUNCH_CONFIG_ENV,
    build_sprite_arg_parser,
    load_sprite_launch_config,
)


def _tr(key, **_kwargs):
    return key


class SpriteCliTests(unittest.TestCase):
    def test_parser_accepts_mirror_stream_endpoint(self):
        parser = build_sprite_arg_parser(_tr)

        args = parser.parse_args(
            [
                "--stream-endpoint",
                "ws://127.0.0.1:8788/ws?sessionId=s1&role=producer",
                "--init-stream-endpoint",
                "ws://127.0.0.1:8788/ws?sessionId=init&role=producer",
                "--mirror-stream-endpoint",
                "ws://127.0.0.1:8788/ws?sessionId=s1&role=producer",
            ]
        )

        self.assertEqual(args.stream_endpoint, "ws://127.0.0.1:8788/ws?sessionId=s1&role=producer")
        self.assertEqual(args.init_stream_endpoint, "ws://127.0.0.1:8788/ws?sessionId=init&role=producer")
        self.assertEqual(args.mirror_stream_endpoint, "ws://127.0.0.1:8788/ws?sessionId=s1&role=producer")

    def test_bridge_launch_config_is_loaded_from_json_environment(self):
        payload = {
            "history": "data/chat_history/session",
            "stream_endpoint": "ws://127.0.0.1:8788/ws?sessionId=s1&role=producer",
            "workflow": "assets/system/workflow/default.yaml",
        }

        with patch.dict(
            os.environ,
            {CHAT_LAUNCH_CONFIG_ENV: json.dumps(payload)},
            clear=False,
        ):
            self.assertEqual(load_sprite_launch_config(), payload)
            self.assertNotIn(CHAT_LAUNCH_CONFIG_ENV, os.environ)

    def test_bridge_launch_config_rejects_unknown_or_non_string_values(self):
        with patch.dict(
            os.environ,
            {CHAT_LAUNCH_CONFIG_ENV: '{"unknown": "value"}'},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                load_sprite_launch_config()

        with patch.dict(
            os.environ,
            {CHAT_LAUNCH_CONFIG_ENV: '{"history": ["not", "a", "string"]}'},
            clear=False,
        ):
            with self.assertRaises(ValueError):
                load_sprite_launch_config()


if __name__ == "__main__":
    unittest.main()
