from application.model_providers import adapter_catalog


def test_adapter_catalog_exposes_visual_backends_and_deepseek_schema():
    options = {item["value"]: item for item in adapter_catalog()["vision"]}

    assert {"auto", "deepseek", "moondream"} <= options.keys()
    assert options["deepseek"]["schema"]["detail"]["choices"] == [
        "auto",
        "low",
        "high",
        "original",
    ]
