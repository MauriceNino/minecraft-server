from __future__ import annotations

from pathlib import Path

from orchestrator.constants import MSMP_SECRET_FILENAME, PUMPKIN_CONFIG_FILENAME, SERVER_PLATFORMS, PlatformType
from orchestrator.logging import console
from orchestrator.merger import merge_file_content
from orchestrator.remote_access.rcon import write_secret_file


def inject_msmp(platform: PlatformType, runtime_dir: Path, port: int, secret: str, *, enabled: bool = True) -> None:
    """Turn the Minecraft Server Management Protocol on or off, unencrypted on all interfaces like RCON.

    Turning it off matters as the config files persist, so an earlier start may have turned it on, and Pumpkin turns
    it on by itself. The secret is alphanumeric (validated in the config), so it needs no escaping in either format.
    """
    flag = "true" if enabled else "false"
    if platform == PlatformType.PUMPKIN:
        merge_file_content(
            runtime_dir / PUMPKIN_CONFIG_FILENAME,
            f'[networking.management]\nenabled = {flag}\naddress = "0.0.0.0:{port}"\nsecret = "{secret}"\n',
        )
    elif platform in SERVER_PLATFORMS:
        # TLS is on by default and needs a keystore, the empty host would only listen on localhost
        merge_file_content(
            runtime_dir / "server.properties",
            f"management-server-enabled={flag}\n"
            "management-server-host=0.0.0.0\n"
            f"management-server-port={port}\n"
            f"management-server-secret={secret}\n"
            "management-server-tls-enabled=false\n",
        )
    else:
        return

    secret_file = runtime_dir / MSMP_SECRET_FILENAME
    if enabled:
        write_secret_file(secret_file, secret)
        console.print(f"  [success]✓[/success] Enabled on port [label]{port}[/label]")
    else:
        secret_file.unlink(missing_ok=True)
        console.print("  [success]✓[/success] Disabled")
