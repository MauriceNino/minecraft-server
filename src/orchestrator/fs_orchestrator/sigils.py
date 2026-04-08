"""Directory and file-level sigil parsing for the filesystem orchestrator."""

from __future__ import annotations

from enum import Enum

# Directory sigils — encoded in directory / file *names*
REPLACE_PREFIX = "!replace:"
FORCE_PREFIX = "!force:"
DELETE_PREFIX = "!delete:"


class DirSigil(Enum):
    """Sigil type parsed from a directory or file name."""

    NONE = "none"
    REPLACE = "replace"
    FORCE = "force"
    DELETE = "delete"


def parse_dir_sigil(name: str) -> tuple[DirSigil, str]:
    """Parse a directory/file name and return `(sigil, clean_name)`.

    Examples
    --------
    >>> parse_dir_sigil("!replace:worldedit")
    (DirSigil.REPLACE, 'worldedit')
    >>> parse_dir_sigil("!replace:bukkit.yaml")
    (DirSigil.REPLACE, 'bukkit.yaml')
    >>> parse_dir_sigil("plugins")
    (DirSigil.NONE, 'plugins')
    >>> parse_dir_sigil("!force:paper-global.yml")
    (DirSigil.FORCE, 'paper-global.yml')
    >>> parse_dir_sigil("!delete:old-config.yml")
    (DirSigil.DELETE, 'old-config.yml')
    """

    if name.startswith(REPLACE_PREFIX):
        clean = name[len(REPLACE_PREFIX) :]
        return DirSigil.REPLACE, clean

    if name.startswith(FORCE_PREFIX):
        clean = name[len(FORCE_PREFIX) :]
        return DirSigil.FORCE, clean

    if name.startswith(DELETE_PREFIX):
        clean = name[len(DELETE_PREFIX) :]
        return DirSigil.DELETE, clean

    return DirSigil.NONE, name
