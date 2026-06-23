import unittest

from core.sprite.sprite_cli import build_sprite_arg_parser


def _tr(key, **_kwargs):
    return key


class SpriteCliTests(unittest.TestCase):
    def test_parser_accepts_mirror_stream_endpoint(self):
        parser = build_sprite_arg_parser(_tr)

        args = parser.parse_args(
            [
                "--stream-endpoint",
                "ws://127.0.0.1:8788/ws?sessionId=s1&role=producer",
                "--mirror-stream-endpoint",
                "ws://127.0.0.1:8788/ws?sessionId=s1&role=producer",
            ]
        )

        self.assertEqual(args.stream_endpoint, "ws://127.0.0.1:8788/ws?sessionId=s1&role=producer")
        self.assertEqual(args.mirror_stream_endpoint, "ws://127.0.0.1:8788/ws?sessionId=s1&role=producer")


if __name__ == "__main__":
    unittest.main()
