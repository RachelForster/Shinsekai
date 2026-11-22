from core.media.effect_keywords import match_effect_label, normalize_effect_label

WEREWOLF_LABELS = (
    "被查验者为“狼”",
    "被查验者为“人”",
    "腹上的花纹为“蛇”",
    "腹上的花纹为“狼”",
    "腹上的花纹为“猿猴”",
    "腹上的花纹为“蜘蛛”",
)


def test_normalize_folds_quotes_punctuation_and_width() -> None:
    assert normalize_effect_label("  被查验者为“狼”。") == "被查验者为狼"
    assert normalize_effect_label("ＫＥＹＢＯＡＲＤ") == "keyboard"


def test_matches_quote_and_width_variants_exactly() -> None:
    assert match_effect_label("被查验者为狼", WEREWOLF_LABELS) == "被查验者为“狼”"
    assert match_effect_label("被查验者为“人”", WEREWOLF_LABELS) == "被查验者为“人”"


def test_matches_paraphrased_wording() -> None:
    assert match_effect_label("查验结果为狼", WEREWOLF_LABELS) == "被查验者为“狼”"
    assert match_effect_label("腹上的花纹是蛇", WEREWOLF_LABELS) == "腹上的花纹为“蛇”"


def test_matches_a_unique_single_character_mention() -> None:
    assert match_effect_label("蛇", WEREWOLF_LABELS) == "腹上的花纹为“蛇”"


def test_rejects_ambiguous_single_character_mentions() -> None:
    assert match_effect_label("狼", WEREWOLF_LABELS) is None


def test_rejects_unrelated_and_short_substring_false_positives() -> None:
    assert match_effect_label("键盘敲击", WEREWOLF_LABELS) is None
    assert match_effect_label("keyboard", ("key",)) is None


def test_accepts_a_configured_label_inside_a_longer_phrase() -> None:
    assert match_effect_label("open door", ("door",)) == "door"
