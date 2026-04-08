"""RCON package — injection and CLI client.

- `inject_rcon` — auto-inject RCON config at startup.
- `mc-rcon` / `python -m orchestrator.rcon` — interactive RCON client.
"""

from orchestrator.rcon.injector import inject_rcon

__all__ = ["inject_rcon"]
