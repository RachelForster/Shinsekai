"""Unit tests for adapter_extra_kwargs — parameter filtering for adapter constructors."""

import pytest

from config.adapter_extra_kwargs import filter_kwargs_for_ctor


class TargetWithKnownParams:
    def __init__(self, name: str = "", size: int = 10):
        self.name = name
        self.size = size


class TargetWithKwargs:
    def __init__(self, name: str = "", **kwargs):
        self.name = name
        self.extras = kwargs


class TestFilterKwargsForCtor:
    def test_passes_matching_params(self):
        result = filter_kwargs_for_ctor(TargetWithKnownParams, {"name": "test", "size": 5})
        assert result == {"name": "test", "size": 5}

    def test_strips_unknown_params(self):
        result = filter_kwargs_for_ctor(TargetWithKnownParams, {"name": "test", "unknown": 42, "garbage": True})
        assert "unknown" not in result
        assert "garbage" not in result
        assert result["name"] == "test"

    def test_partial_extra(self):
        result = filter_kwargs_for_ctor(TargetWithKnownParams, {"size": 99})
        assert result == {"size": 99}

    def test_empty_extra_returns_empty(self):
        result = filter_kwargs_for_ctor(TargetWithKnownParams, {})
        assert result == {}

    def test_var_keyword_passes_all(self):
        """When __init__ has **kwargs, all extras pass through."""
        result = filter_kwargs_for_ctor(TargetWithKwargs, {"name": "x", "anything": "yes", "flag": True})
        assert result == {"name": "x", "anything": "yes", "flag": True}

    def test_no_match_returns_empty(self):
        result = filter_kwargs_for_ctor(TargetWithKnownParams, {"completely": "different"})
        assert result == {}

    def test_builtin_type(self):
        """Should work with built-in constructors that have inspectable signatures."""
        result = filter_kwargs_for_ctor(dict, {})
        assert result == {}

    def test_no_init_inherits_object_kwargs(self):
        """Class without own __init__ inherits object.__init__(**kwargs), passes all."""
        class NoInit:
            pass
        result = filter_kwargs_for_ctor(NoInit, {"x": 1})
        assert result == {"x": 1}  # inherits **kwargs from object
