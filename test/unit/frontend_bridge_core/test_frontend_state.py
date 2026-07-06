from frontend_bridge_core.state import _jsonify


class ModelDumpValue:
    def model_dump(self, *, mode: str):
        assert mode == "json"
        return {"nested": [{"value": 1}]}


def test_jsonify_recursively_handles_model_dump_lists_and_dicts():
    assert _jsonify(
        {
            1: ModelDumpValue(),
            "items": [ModelDumpValue(), {"ok": True}],
        }
    ) == {
        "1": {"nested": [{"value": 1}]},
        "items": [{"nested": [{"value": 1}]}, {"ok": True}],
    }


def test_jsonify_returns_scalar_values_unchanged():
    assert _jsonify("text") == "text"
    assert _jsonify(3) == 3
    assert _jsonify(None) is None
