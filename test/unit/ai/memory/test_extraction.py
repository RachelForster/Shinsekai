from __future__ import annotations

from ai.memory.chunking import chunk_dialogue_units
from ai.memory.extraction import MemoryExtractor, parse_extracted_memories
from ai.memory.token_estimator import estimate_text_tokens
from test.mocks import MockLLMAdapter


def test_chunking_preserves_order_and_splits_oversized_turns():
    units = ["user: " + ("甲" * 600), "Mika: second turn", "user: final turn"]

    chunks = chunk_dialogue_units(units, max_tokens=256)

    assert len(chunks) >= 3
    assert "second turn" in "\n".join(chunks)
    assert "final turn" in chunks[-1]
    assert all(estimate_text_tokens(chunk) <= 256 for chunk in chunks)


def test_parse_extracted_memories_accepts_wrapped_fenced_json_and_forces_target():
    response = """```json
    {"memories":[
      {"character_name":"Other","memory":"Likes rain","confidence":2},
      {"content":"Keeps promises","confidence":"bad"}
    ]}
    ```"""

    rows = parse_extracted_memories(
        response,
        default_character_name="Mika",
        force_character_name="Nanami",
    )

    assert [row["character_name"] for row in rows] == ["Nanami", "Nanami"]
    assert rows[0]["confidence"] == 1.0
    assert rows[1]["confidence"] == 1.0


def test_extractor_splits_long_dialogue_and_deduplicates_across_chunks():
    adapter = MockLLMAdapter(
        responses=['[{"memory":"User likes tea"}]', '[{"memory":"User likes tea"}]']
    )
    extractor = MemoryExtractor(adapter)
    dialogue = "\n".join(["user: " + ("hello " * 180), "Mika: " + ("reply " * 180)])

    rows, duplicates, chunk_count = extractor.extract_dialogue(
        dialogue,
        default_character_name="Mika",
        max_chunk_tokens=256,
    )

    assert chunk_count >= 2
    assert len(adapter.call_history) == chunk_count
    assert rows == [{"character_name": "Mika", "memory": "User likes tea", "confidence": 1.0}]
    assert duplicates == chunk_count - 1

