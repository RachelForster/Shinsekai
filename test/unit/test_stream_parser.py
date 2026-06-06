"""Unit tests for LlmResponseStreamParser — JSON extraction from LLM chunks."""

import pytest

from core.messaging.stream_parser import LlmResponseStreamParser
from sdk.messages import LLMDialogMessage


class TestLlmResponseStreamParser:
    def test_single_complete_json(self):
        parser = LlmResponseStreamParser()
        results = list(parser.feed('{"character_name": "Alice", "speech": "Hi!", "sprite": "0"}'))
        assert len(results) == 1
        msg = results[0]
        assert isinstance(msg, LLMDialogMessage)
        assert msg.name == "Alice"
        assert msg.text == "Hi!"
        assert msg.asset_id == "0"

    def test_split_across_chunks(self):
        parser = LlmResponseStreamParser()
        results = []
        results += list(parser.feed('{"character_n'))
        results += list(parser.feed('ame": "Bob", "speech": "Hello", "sprite": "-1"}'))
        assert len(results) == 1
        assert results[0].name == "Bob"
        assert results[0].text == "Hello"

    def test_multiple_jsons_one_chunk(self):
        parser = LlmResponseStreamParser()
        chunk = (
            '{"character_name": "A", "speech": "One", "sprite": "0"}'
            '{"character_name": "B", "speech": "Two", "sprite": "1"}'
        )
        results = list(parser.feed(chunk))
        assert len(results) == 2
        assert results[0].name == "A"
        assert results[1].name == "B"

    def test_text_between_jsons_is_skipped(self):
        parser = LlmResponseStreamParser()
        chunk = 'some text {"character_name": "NARR", "speech": "Story", "sprite": "-1"} more text'
        results = list(parser.feed(chunk))
        assert len(results) == 1
        assert results[0].name == "NARR"

    def test_malformed_json_is_skipped(self):
        parser = LlmResponseStreamParser()
        results = list(parser.feed('{broken json} {"character_name": "X", "speech": "Ok", "sprite": "0"}'))
        assert len(results) == 1
        assert results[0].name == "X"
        assert parser.has_errors

    def test_brace_inside_string_does_not_end_json(self):
        parser = LlmResponseStreamParser()
        results = list(parser.feed('{"character_name": "A", "speech": "brace } in text", "sprite": "0"}'))

        assert len(results) == 1
        assert results[0].text == "brace } in text"
        assert not parser.has_errors

    def test_nested_extra_object_is_parsed_as_single_json(self):
        parser = LlmResponseStreamParser()
        results = list(
            parser.feed(
                '{"character_name": "A", "speech": "Hi", "sprite": "0", '
                '"metadata": {"mood": "calm", "score": 2}}'
            )
        )

        assert len(results) == 1
        assert results[0].model_extra == {"metadata": {"mood": "calm", "score": 2}}

    def test_split_json_with_brace_inside_string(self):
        parser = LlmResponseStreamParser()
        results = []
        results += list(parser.feed('{"character_name": "A", "speech": "part }'))
        results += list(parser.feed(' still string", "sprite": "0"}'))

        assert len(results) == 1
        assert results[0].text == "part } still string"

    def test_unclosed_bad_prefix_can_recover_later_json(self):
        parser = LlmResponseStreamParser()
        results = list(parser.feed('{broken {"character_name": "X", "speech": "Recovered", "sprite": "0"}'))

        assert len(results) == 1
        assert results[0].name == "X"

    def test_empty_chunk_yields_nothing(self):
        parser = LlmResponseStreamParser()
        results = list(parser.feed(""))
        assert len(results) == 0

    def test_no_braces_yields_nothing(self):
        parser = LlmResponseStreamParser()
        results = list(parser.feed("just some plain text"))
        assert len(results) == 0

    def test_accumulated_text_tracks_all_input(self):
        parser = LlmResponseStreamParser()
        list(parser.feed('{"character_name": "N", "speech": "T", "sprite": "0"}'))
        list(parser.feed(" extra "))
        assert "extra" in parser.accumulated_text
        assert "character_name" in parser.accumulated_text

    def test_alias_fields_work(self):
        """character_name alias maps to name, speech alias maps to text."""
        parser = LlmResponseStreamParser()
        results = list(parser.feed('{"character_name": "TestChar", "speech": "Aliased text", "sprite": "5"}'))
        assert results[0].name == "TestChar"
        assert results[0].text == "Aliased text"
        assert results[0].asset_id == "5"
