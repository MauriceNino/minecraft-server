from __future__ import annotations

import re

from orchestrator.plugins.base import PluginSpec

# Matches:  provider:id@version,  provider:id[key=val]@version,  or variants with !
_SPEC_RE = re.compile(
    r"^(?P<provider>[a-z]+):(?P<id>[^\[@]+?)(?:\[(?P<params>[^\]]*)\])?(?:@(?P<version>[^!]+?)(?P<force>!)?)?$"
)

# URL provider is detected by the presence of :// in the identifier
_URL_RE = re.compile(r"^url:(?P<url>https?://.+)$")

# Canonical stable aliases -> "latest"
_STABLE_ALIASES: frozenset[str] = frozenset({"latest", "stable"})
# Canonical experimental aliases -> "experimental"
_EXPERIMENTAL_ALIASES: frozenset[str] = frozenset({"experimental", "beta"})


def _parse_params(raw_params: str | None) -> dict[str, str]:
    if not raw_params:
        return {}
    result: dict[str, str] = {}
    for part in raw_params.split(","):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, value = part.partition("=")
        result[key.strip()] = value.strip()
    return result


def _normalize_plugin_version(raw: str) -> str:
    """Normalise a plugin version specifier to a canonical sentinel or leave it as-is.

    - `latest` / `stable` -> `latest`
    - `experimental` / `beta` -> `experimental`
    - anything else (e.g. `5.4.137`) -> unchanged
    """
    lower = raw.strip().lower()
    if lower in _STABLE_ALIASES:
        return "latest"
    if lower in _EXPERIMENTAL_ALIASES:
        return "experimental"
    return raw.strip()


def parse_plugin_spec(raw: str) -> PluginSpec:
    """Parse a raw plugin line into a :class:`PluginSpec`.

    Supported formats::

        modrinth:luckperms@latest
        modrinth:luckperms@stable        # alias for latest
        modrinth:luckperms@experimental  # pre-release / beta channel
        modrinth:luckperms@beta          # alias for experimental
        modrinth:luckperms@5.4!
        hangar:libertybans@latest
        spiget:28140@latest
        url:https://example.com/plugin.jar
        github:MilkBowl/Vault@latest
        github:SkinsRestorer/SkinsRestorer[regex=/SkinsRestorer-Forg-.*.jar/]@latest

    """
    raw = raw.strip()
    if not raw:
        msg = "Empty plugin spec"
        raise ValueError(msg)

    # Handle URL provider specially
    url_match = _URL_RE.match(raw)
    if url_match:
        return PluginSpec(
            provider="url",
            identifier=url_match.group("url"),
            version="latest",
            force=False,
        )

    match = _SPEC_RE.match(raw)
    if not match:
        msg = f"Invalid plugin spec: {raw!r}. Expected format: provider:id[params]@version"
        raise ValueError(msg)

    raw_version = match.group("version") or "latest"
    return PluginSpec(
        provider=match.group("provider"),
        identifier=match.group("id").strip(),
        version=_normalize_plugin_version(raw_version),
        force=match.group("force") is not None,
        params=_parse_params(match.group("params")),
    )


def parse_plugin_lines(lines: list[str]) -> list[PluginSpec]:
    """Parse multiple plugin spec lines, skipping blanks and comments."""
    specs: list[PluginSpec] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        specs.append(parse_plugin_spec(line))
    return specs
