from core.messaging.stat_payload import format_stats_html, parse_stat_payload


def test_parse_stat_payload_accepts_preferred_lines_and_optional_maximum():
    assert parse_stat_payload("heart|HP|72|100\ncoins|Gold|320") == [
        {"icon": "heart", "label": "HP", "max": 100, "value": 72},
        {"icon": "coins", "label": "Gold", "value": 320},
    ]


def test_parse_stat_payload_keeps_legacy_html_compatible_and_infers_icons():
    assert parse_stat_payload(
        "<span style='color:#fff'>生命：25/100</span><br><span>好感度: 12.5/50</span>"
    ) == [
        {"icon": "heart", "label": "生命", "max": 100, "value": 25},
        {"icon": "sparkles", "label": "好感度", "max": 50, "value": 12.5},
    ]


def test_parse_stat_payload_ignores_malformed_or_non_finite_values_and_caps_items():
    payload = "\n".join(
        [
            "unknown|Mood|5|10",
            "heart||7|10",
            "zap|Energy|NaN|100",
            "star|Level|2|0",
            "coins|Gold|3",
        ]
    )

    assert parse_stat_payload(payload, max_items=3) == [
        {"icon": "gauge", "label": "Mood", "max": 10, "value": 5},
        {"icon": "star", "label": "Level", "value": 2},
        {"icon": "coins", "label": "Gold", "value": 3},
    ]


def test_format_stats_html_supports_the_legacy_desktop_panel():
    assert (
        format_stats_html(
            [
                {"icon": "heart", "label": "HP", "max": 100, "value": 72},
                {"icon": "coins", "label": "Gold", "value": 8},
            ]
        )
        == "<span>HP: 72 / 100</span><br><span>Gold: 8</span>"
    )
