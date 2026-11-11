"""WebAssembly plugins for Pumpkin from the Pumpkin Market (https://market.pumpkinmc.org)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict, cast

import httpx
from rich.markup import escape

from orchestrator.constants import PlatformType, PluginProviderType
from orchestrator.http import PUMPKIN_MARKET_HOST
from orchestrator.lockfile import ServerLockfile, make_lock_key
from orchestrator.logging import log_change
from orchestrator.merger import merge_file_content
from orchestrator.plugins.base import AbstractPluginProvider, PluginSpec, ResolvedPlugin

API_BASE = f"https://{PUMPKIN_MARKET_HOST}/api/v1/rest"


def _plugin_id(identifier: str) -> str:
    """Accept both `ID0WVaaw` and the `ID0WVaaw-perfmon` of the market URL: IDs have no dash, the slug is ignored."""
    return identifier.partition("-")[0]


def _filename(name: str) -> str:
    return f"{re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_') or 'plugin'}.wasm"


class PumpkinMarketProvider(AbstractPluginProvider):
    async def _get_plugin(self, client: httpx.AsyncClient, identifier: str) -> MarketPlugin:
        plugin_id = _plugin_id(identifier)
        if not plugin_id:
            raise RuntimeError(f"'{identifier}' is not a Pumpkin Market plugin ID, e.g. ID0WVaaw-perfmon")
        resp = await client.get(f"{API_BASE}/plugins/{plugin_id}")
        if resp.status_code == 404:
            raise RuntimeError(f"Plugin '{plugin_id}' was not found on the Pumpkin Market")
        resp.raise_for_status()
        return cast(MarketPlugin, resp.json())

    async def resolve(
        self,
        spec: PluginSpec,
        platform_type: PlatformType,
        mc_version: str,
        client: httpx.AsyncClient,
    ) -> ResolvedPlugin:
        if not spec.force and platform_type != PlatformType.PUMPKIN:
            raise self._platform_not_supported(spec, [PlatformType.PUMPKIN])

        plugin = await self._get_plugin(client, spec.identifier)
        # The market only serves the current version. A plugin without a version is identified by its last update.
        version = plugin.get("version") or plugin["updated_at"]
        if spec.version not in ("latest", "experimental") and spec.version != version:
            raise RuntimeError(
                f"Plugin {spec.identifier} is at version '{version}', the Pumpkin Market only offers the current"
                f" version. Use @latest, or @{version} to pin it to that."
            )

        return ResolvedPlugin(
            display_name=plugin["name"],
            version=version,
            download_url=f"{API_BASE}/plugins/{plugin['public_id']}/download",
            filename=_filename(plugin["name"]),
        )

    async def download(self, resolved: ResolvedPlugin, dest: Path, client: httpx.AsyncClient) -> Path:
        try:
            return await super().download(resolved, dest, client)
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in (401, 402, 403):
                raise
            # The market explains why in plain text, e.g. that a plugin is not published yet. Cloudflare's error pages
            # are HTML, those only get the status.
            resp = await client.get(resolved.download_url)
            plain = resp.headers.get("Content-Type", "").startswith("text/plain")
            reason = (
                resp.text.strip()[:200] if plain else ""
            ) or f"{e.response.status_code} {e.response.reason_phrase}"
            raise RuntimeError(
                f"The Pumpkin Market refused the download of {resolved.display_name}: {reason}. Paid plugins need"
                " PUMPKIN_MARKET_TOKEN, an API key of the account that owns them."
            ) from None


@dataclass(frozen=True, slots=True)
class PermissionGrant:
    lock_key: str
    name: str  # the name Pumpkin keys the override by
    permissions: list[str]


def permission_grants(specs: list[PluginSpec], lockfile: ServerLockfile) -> list[PermissionGrant]:
    """The permissions the `allow` parameters grant.

    Pumpkin asks for a plugin's permissions on the console, which a container doesn't have, so it denies them unless
    they are pre-allowed. The override is keyed by the plugin's own name, which is only known once Pumpkin runs it: the
    `name` parameter, else the market name in lowercase (`Perfmon` declares itself as `perfmon`).
    """
    grants: list[PermissionGrant] = []
    for spec in specs:
        allow = spec.param("allow")
        if spec.provider != PluginProviderType.PUMPKIN or allow is None:
            continue
        lock_key = make_lock_key(spec.provider, spec.identifier)
        entry = lockfile.get_plugin(lock_key)
        # Before the first download, the slug of the market URL is the best guess
        fallback = spec.identifier.partition("-")[2] or spec.identifier
        name = spec.param("name") or (entry.display_name if entry else fallback).lower()
        grants.append(PermissionGrant(lock_key, name, [p.strip() for p in allow.split(",") if p.strip()]))
    return grants


def apply_permission_grants(grants: list[PermissionGrant], pumpkin_config: Path) -> None:
    """Write *grants* to `[plugins.overrides.<name>]` of `pumpkin.toml` and log each of them."""
    if not grants:
        return
    merge_file_content(
        pumpkin_config,
        "\n".join(
            f"[plugins.overrides.{json.dumps(g.name)}]\nallowed_permissions = {json.dumps(g.permissions)}\n"
            for g in grants
        ),
    )
    for grant in grants:
        permissions = ", ".join(grant.permissions) or "no permissions"
        log_change("granted", grant.lock_key, escape(f"{grant.name}: {permissions}"))


class MarketPlugin(TypedDict):
    id: int
    public_id: str
    name: str
    version: str | None
    api_version: str | None
    category: str
    type: str  # "free", "paid" or "adwall"
    price: float
    downloads: int
    dev_name: str
    created_at: str
    updated_at: str
