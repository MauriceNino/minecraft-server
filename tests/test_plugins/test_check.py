from __future__ import annotations

from orchestrator.constants import PluginProviderType
from orchestrator.lockfile import PluginLockEntry, make_lock_key
from orchestrator.plugins import PluginResolution
from orchestrator.plugins.base import PluginSpec, ResolvedPlugin
from orchestrator.plugins.check import classify_updates


def _resolution(
    name: str,
    installed: str | None,
    resolving: str | None,
    *,
    provider: PluginProviderType = PluginProviderType.MODRINTH,
    identifier: str | None = None,
) -> PluginResolution:
    spec = PluginSpec(provider=provider, identifier=identifier or name.lower(), version="latest", force=False)
    entry = (
        PluginLockEntry(name, installed, None, f"{name}.jar", "2026-01-01T00:00:00Z", "latest") if installed else None
    )
    resolved = ResolvedPlugin(name, resolving, "https://cdn.example/x.jar", f"{name}.jar") if resolving else None
    return PluginResolution(
        spec,
        make_lock_key(spec.provider, spec.identifier),
        entry,
        resolved,
        None if resolving else "404 Not Found",
    )


def test_classifies_each_group() -> None:
    url = "https://example.com/some/really/long/path/Broken.jar"
    resolutions = [
        _resolution("Update", "1.0", "2.0"),
        _resolution("Pinned", "1.0", "1.0"),
        _resolution("New", None, "1.0"),
        _resolution("Broken", None, None, provider=PluginProviderType.URL, identifier=url),
        _resolution("Current", "3.0", "3.0"),
    ]
    latest = {"modrinth:pinned": "1.5", "modrinth:current": "3.0"}

    groups = classify_updates(resolutions, latest)

    assert [(e.name, e.detail) for e in groups.updates] == [("Update", "1.0 → 2.0")]
    assert [(e.name, e.detail) for e in groups.pinned] == [("Pinned", "1.0 (latest 1.5)")]
    assert [(e.name, e.detail) for e in groups.new] == [("New", "→ 1.0")]
    assert [(e.lock_key, e.detail) for e in groups.errors] == [(f"url:{url}", "Error: 404 Not Found")]
    assert [e.name for e in groups.up_to_date] == ["Current"]


def test_sorts_by_name_case_insensitively() -> None:
    resolutions = [_resolution("beta", "1.0", "2.0"), _resolution("Alpha", "1.0", "2.0")]

    groups = classify_updates(resolutions, {})

    assert [e.name for e in groups.updates] == ["Alpha", "beta"]


def test_keeps_error_markup_and_escapes_versions() -> None:
    error = _resolution("Broken", None, None)
    error = PluginResolution(error.spec, error.lock_key, None, None, "use [info]@latest![/info] to force")
    resolutions = [error, _resolution("Odd", "1.0-[beta]", "2.0-[beta]")]

    groups = classify_updates(resolutions, {})

    assert groups.errors[0].detail == "Error: use [info]@latest![/info] to force"
    assert groups.updates[0].detail == "1.0-\\[beta] → 2.0-\\[beta]"
