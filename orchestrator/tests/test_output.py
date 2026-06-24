"""Tests for output coercion."""

from __future__ import annotations

import pytest

from src.core.output import OutputError, coerce_output


def test_coerce_output_parses_json_string() -> None:
    assert coerce_output('{"ok": true}') == {"ok": True}


def test_coerce_output_passes_through_plain_text() -> None:
    assert coerce_output("plain text") == "plain text"


def test_coerce_output_passes_through_dict() -> None:
    assert coerce_output({"summary": "done"}) == {"summary": "done"}


def test_coerce_output_raises_when_missing() -> None:
    with pytest.raises(OutputError, match="no output"):
        coerce_output(None)
