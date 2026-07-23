from __future__ import annotations

from core.runtime.requirements import (
    check_requirement,
    unsatisfied_requirements,
)


def test_requirement_check_rejects_an_installed_incompatible_version():
    check = check_requirement(
        "huggingface-hub==0.36.2",
        {"huggingface-hub": "1.24.0"},
    )

    assert check.name == "huggingface-hub"
    assert check.installed_version == "1.24.0"
    assert check.satisfied is False
    assert "does not satisfy" in check.issue


def test_requirement_check_accepts_compatible_ranges_and_normalized_names():
    versions = {
        "sentence_transformers": "5.2.2",
        "Transformers": "4.57.1",
    }

    assert check_requirement(
        "sentence-transformers>=5.2,<6",
        versions,
    ).satisfied
    assert check_requirement("transformers>=4.51.1,<5", versions).satisfied


def test_requirement_check_rejects_an_invalid_installed_version():
    check = check_requirement(
        "huggingface-hub==0.36.2",
        {"huggingface-hub": "not-a-version"},
    )

    assert check.satisfied is False


def test_unsatisfied_requirements_reports_missing_and_incompatible_packages():
    issues = unsatisfied_requirements(
        [
            "mem0ai[nlp]",
            "spacy>=3.7,<4",
            "huggingface-hub==0.36.2",
        ],
        {
            "mem0ai": "2.0.12",
            "huggingface-hub": "1.24.0",
        },
    )

    assert [issue.name for issue in issues] == ["spacy", "huggingface-hub"]
    assert issues[0].installed_version is None
    assert issues[1].installed_version == "1.24.0"
