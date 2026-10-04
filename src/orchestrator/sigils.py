from __future__ import annotations

from enum import Enum

REPLACE_PREFIX = "!replace:"
FORCE_PREFIX = "!force:"
DELETE_PREFIX = "!delete:"


class DirSigil(Enum):
    """Sigil in a template file/directory name or a CONFIG_PATHS key."""

    NONE = "none"
    REPLACE = "replace"
    FORCE = "force"
    DELETE = "delete"


_PREFIXES = {
    REPLACE_PREFIX: DirSigil.REPLACE,
    FORCE_PREFIX: DirSigil.FORCE,
    DELETE_PREFIX: DirSigil.DELETE,
}


def parse_dir_sigil(name: str) -> tuple[DirSigil, str]:
    """Split off the sigil, e.g. `"!force:paper-global.yml"` -> `(DirSigil.FORCE, "paper-global.yml")`."""
    for prefix, sigil in _PREFIXES.items():
        if name.startswith(prefix):
            return sigil, name.removeprefix(prefix)
    return DirSigil.NONE, name
