<div align="center">
  <h1>
    <img src="docs/public/banner.png" alt="MauriceNino/minecraft-server" width="100%" style="border-radius: 25px;">
  </h1>
  
  <p><b>Docker image that sets up and runs Minecraft servers and proxies from environment variables: server JAR, plugins, config templates and RCON.</b></p>

  [![License](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
  [![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
</div>

---

## Overview

On every start, the container downloads the server JAR, installs and updates your plugins, applies your config templates and then launches the server. Everything is declared in environment variables, so the whole server lives in your `docker-compose.yml`.

📖 **[Documentation](https://mauricenino.github.io/minecraft-server/)**

## Features

- **Platforms**: Paper, Purpur, Folia, Spigot, Bukkit, Vanilla, Pumpkin (experimental), Velocity, Waterfall and BungeeCord.
- **Plugins**: from Modrinth, Hangar, Spiget, CurseForge, GitHub releases or direct URLs, with compatibility checks against your server version and a lockfile to track what's installed.
- **Config merging**: deep-merge `YAML`, `JSON`, `TOML`, `HOCON` and `.properties` files from templates or environment variables, controlled with `!replace:`, `!force:` and `!delete:` sigils.
- **RCON**: enabled automatically, use `docker exec -it <container> mc-rcon` to get a console.

## Getting Started

The quickest way to get started is using Docker Compose. Here is a minimal example:

```yaml
services:
  minecraft:
    image: ghcr.io/mauricenino/minecraft-server:latest
    environment:
      TYPE: PAPER
      VERSION: latest
      MEMORY: 2G
      ACCEPT_EULA: "true"
      PLUGINS: |
        modrinth:luckperms@latest
    ports:
      - "25565:25565"
```

See the **[Documentation](https://mauricenino.github.io/minecraft-server/)** for all environment variables, templates and sigils.
