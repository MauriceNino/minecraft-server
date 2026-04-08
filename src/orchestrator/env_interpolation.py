from __future__ import annotations

import os
import re

from orchestrator.logging import get_logger

log = get_logger(__name__)

# Matches $[VARIABLE_NAME] — variable name may contain letters, digits and underscores
_ENV_PATTERN = re.compile(r"\$\[([A-Za-z_][A-Za-z0-9_]*)\]")


def interpolate_env(text: str, environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ

    def _replace(match: re.Match[str]) -> str:
        var_name = match.group(1)
        if var_name in env:
            return env[var_name]
        log.warning(
            "Environment variable %r referenced in template/config but not set — leaving as-is",
            var_name,
        )
        return match.group(0)

    return _ENV_PATTERN.sub(_replace, text)
