from pathlib import Path

from pyhocon import ConfigFactory

from orchestrator.merger.conf_merger import merge_conf


def test_merge_conf_basic(tmp_path: Path) -> None:
    existing = tmp_path / "config.conf"
    existing.write_text('foo = "bar"\nbaz = 1', encoding="utf-8")

    overlay = 'foo = "updated"\nnew = "key"'
    merge_conf(existing, overlay)

    config = ConfigFactory.parse_file(str(existing))
    assert config.get_string("foo") == "updated"
    assert config.get_int("baz") == 1
    assert config.get_string("new") == "key"


def test_merge_conf_nested(tmp_path: Path) -> None:
    existing = tmp_path / "config.conf"
    existing.write_text('parent { child = "original" }', encoding="utf-8")

    overlay = 'parent { new = "val" }'
    merge_conf(existing, overlay)

    config = ConfigFactory.parse_file(str(existing))
    assert config.get_string("parent.child") == "original"
    assert config.get_string("parent.new") == "val"


def test_merge_conf_replace_sigil(tmp_path: Path) -> None:
    existing = tmp_path / "config.conf"
    existing.write_text('parent { child = "to-be-replaced", other = "keep" }', encoding="utf-8")

    # Replace the 'parent' block entirely
    overlay = '!replace:parent { new = "val" }'
    merge_conf(existing, overlay)

    config = ConfigFactory.parse_file(str(existing))
    assert "child" not in config.get("parent")
    assert "other" not in config.get("parent")
    assert config.get_string("parent.new") == "val"


def test_merge_conf_delete_sigil(tmp_path: Path) -> None:
    existing = tmp_path / "config.conf"
    existing.write_text('foo = "bar"\nbaz = 1', encoding="utf-8")

    overlay = "!delete:foo = ignored"
    merge_conf(existing, overlay)

    config = ConfigFactory.parse_file(str(existing))
    assert "foo" not in config
    assert config.get_int("baz") == 1


def test_merge_conf_no_existing(tmp_path: Path) -> None:
    existing = tmp_path / "new.conf"

    overlay = 'foo = "bar"\n!replace:nested { val = 1 }'
    merge_conf(existing, overlay)

    config = ConfigFactory.parse_file(str(existing))
    assert config.get_string("foo") == "bar"
    assert config.get_int("nested.val") == 1
    # Check that sigils were stripped
    assert "!replace:nested" not in config
