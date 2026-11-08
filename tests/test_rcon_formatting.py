"""Tests for converting legacy `§` formatting codes into Rich text."""

from __future__ import annotations

from rich.style import Style

from rcon.formatting import legacy_to_text


def _spans(message: str) -> list[tuple[str, Style | str]]:
    text = legacy_to_text(message)
    return [(text.plain[span.start : span.end], span.style) for span in text.spans]


class TestLegacyToText:
    def test_plain_text_is_unchanged(self) -> None:
        text = legacy_to_text("There are 0 of a max of 20 players online: ")
        assert text.plain == "There are 0 of a max of 20 players online: "
        assert text.spans == []

    def test_legacy_colors(self) -> None:
        text = legacy_to_text(" §8- §aLuckPerms")
        assert text.plain == " - LuckPerms"
        assert _spans(" §8- §aLuckPerms") == [("- ", Style(color="#555555")), ("LuckPerms", Style(color="#55ff55"))]

    def test_hex_colors(self) -> None:
        message = "§x§3§4§9§f§d§a* §fServer Plugins (1):"
        assert legacy_to_text(message).plain == "* Server Plugins (1):"
        assert _spans(message) == [("* ", Style(color="#349fda")), ("Server Plugins (1):", Style(color="#ffffff"))]

    def test_decorations_stack_and_reset(self) -> None:
        message = "§c§lBold red§rplain"
        assert legacy_to_text(message).plain == "Bold redplain"
        assert _spans(message) == [("Bold red", Style(color="#ff5555") + Style(bold=True))]

    def test_uppercase_codes(self) -> None:
        assert _spans("§AGreen") == [("Green", Style(color="#55ff55"))]

    def test_markup_is_not_interpreted(self) -> None:
        assert legacy_to_text("[bold]not markup[/bold]").plain == "[bold]not markup[/bold]"
