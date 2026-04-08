"""Tests for environment variable interpolation."""

from __future__ import annotations

import pytest

from orchestrator.env_interpolation import interpolate_env


class TestInterpolateEnv:
    def test_basic_substitution(self) -> None:
        result = interpolate_env("secret: $[MY_SECRET]", {"MY_SECRET": "s3cr3t"})
        assert result == "secret: s3cr3t"

    def test_multiple_substitutions(self) -> None:
        result = interpolate_env(
            "user=$[DB_USER] pass=$[DB_PASS]",
            {"DB_USER": "admin", "DB_PASS": "hunter2"},
        )
        assert result == "user=admin pass=hunter2"

    def test_same_var_twice(self) -> None:
        result = interpolate_env("$[X] and $[X]", {"X": "hello"})
        assert result == "hello and hello"

    def test_unknown_var_left_unchanged(self) -> None:
        result = interpolate_env("value=$[UNKNOWN_VAR]", {})
        assert result == "value=$[UNKNOWN_VAR]"

    def test_no_placeholders(self) -> None:
        text = "bind = 0.0.0.0:25565\nmotd = Hello!"
        assert interpolate_env(text, {}) == text

    def test_empty_string(self) -> None:
        assert interpolate_env("", {"X": "y"}) == ""

    def test_multiline_yaml(self) -> None:
        template = "proxies:\n  velocity:\n    secret: $[FORWARDING_SECRET]\n"
        result = interpolate_env(template, {"FORWARDING_SECRET": "abc123"})
        assert "secret: abc123" in result

    def test_var_at_end_of_line(self) -> None:
        result = interpolate_env("password=$[RCON_PASSWORD]", {"RCON_PASSWORD": "rcon"})
        assert result == "password=rcon"

    def test_adjacent_placeholders(self) -> None:
        result = interpolate_env("$[A]$[B]", {"A": "Hello", "B": "World"})
        assert result == "HelloWorld"

    def test_defaults_to_os_environ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("_TEST_MC_ORCH_VAR", "from_os")
        result = interpolate_env("value=$[_TEST_MC_ORCH_VAR]")
        assert result == "value=from_os"
