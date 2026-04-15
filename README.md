<div align="center">
  <h1>
    <img src="docs/public/banner.png" alt="MauriceNino/minecraft-server" width="100%" style="border-radius: 25px;">
  </h1>
  
  <p><b>A modular, production-grade Minecraft server orchestrator with dynamic plugin resolution, sigil-based config merging, and automated RCON injection.</b></p>

  [![License](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
  [![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
</div>

---

## Overview

`MauriceNino/minecraft-server` is a powerful Python utility and Docker-first environment designed to streamline the deployment and management of stateless Minecraft server instances. Say goodbye to manual plugin updates and messy configuration files.

📖 **[Check out the Full Documentation Site!](https://mauricenino.github.io/minecraft-server/)**

## Key Features

- **Multi-Platform Support**: Native support for **Paper**, **Purpur**, **Folia**, **Velocity**, **Waterfall**, **Vanilla**, **Spigot**, and **Bukkit**.
- **Dynamic Plugin Resolution**: Seamlessly download and cache plugins from **Modrinth**, **Hangar**, **Spiget**, **CurseForge**, **GitHub**, or direct **URLs**.
- **Sigil-Based Config Merging**: Intelligently merge `YAML`, `JSON`, `TOML`, `HOCON`, and `.properties` files using `!replace:`, `!force:`, and `!delete:` lifecycle sigils.
- **Auto-RCON**: Integrated `mc-rcon` module for secure, automated remote console access inside the container.
- **Docker-First Architecture**: Built for stateless deployments via Docker Compose with deterministic startup routines.

## Getting Started

The quickest way to get started is using Docker Compose. Here is a minimal example:

```yaml
services:
  minecraft:
    image: ghcr.io/MauriceNino/minecraft-server:latest
    environment:
      TYPE: PAPER
      VERSION: latest
      MEMORY: 2G
      PLUGINS: |
        modrinth:luckperms@latest
    ports:
      - "25565:25565"
```

For more in-depth setup guides, including orchestration scripts runbooks, environment variable dictionaries, and sigil usage, please visit the **[Documentation](https://mauricenino.github.io/minecraft-server/)**.
