from __future__ import annotations

import os
import re

from orchestrator.logging import console

# Matches $[VARIABLE_NAME] — variable name may contain letters, digits and underscores
_ENV_PATTERN = re.compile(r"\$\[([A-Za-z_][A-Za-z0-9_]*)\]")


def interpolate_env(text: str, environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name in env:
            return env[var_name]
        console.print(f"  [warning]⚠[/warning] [label]Environment variable {var_name} not set[/label]")
        return match.group(0)

    return _ENV_PATTERN.sub(_replace, text)
