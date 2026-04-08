"""Tests for the sigil-aware config merger."""

from __future__ import annotations

from orchestrator.merger.sigils import KeySigil, parse_key_sigil, strip_sigils


class TestParseKeySigil:
    def test_replace(self) -> None:
        sigil, key = parse_key_sigil("!replace:servers")
        assert sigil == KeySigil.REPLACE
        assert key == "servers"

    def test_delete(self) -> None:
        sigil, key = parse_key_sigil("!delete:legacy")
        assert sigil == KeySigil.DELETE
        assert key == "legacy"

    def test_none(self) -> None:
        sigil, key = parse_key_sigil("motd")
        assert sigil == KeySigil.NONE
        assert key == "motd"


class TestStripSigils:
    def test_nested(self) -> None:
        data = {
            "!replace:servers": {"lobby": "localhost:25565"},
            "!delete:old_cache": {"should": "be gone"},
            "normal": "value",
        }
        result = strip_sigils(data)
        assert result == {
            "servers": {"lobby": "localhost:25565"},
            "normal": "value",
        }

    def test_list(self) -> None:
        data = [{"!replace:key": "val"}]
        result = strip_sigils(data)
        assert result == [{"key": "val"}]
