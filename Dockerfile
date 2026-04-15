# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.12

# Builder
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-trixie-slim AS builder

WORKDIR /build

ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock README.md ./
COPY src/ src/

RUN uv venv /opt/venv && \
    uv pip install --no-cache --python=/opt/venv .

# Runtime
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-trixie-slim AS runtime

ARG JAVA_VERSION=25
ARG JAVA_FLAVOR=temurin

LABEL org.opencontainers.image.title="minecraft-server" \
    org.opencontainers.image.description="Modular Minecraft server orchestrator with plugin resolution, config merging, and RCON injection" \
    org.opencontainers.image.source="https://github.com/MauriceNino/minecraft-server" \
    org.opencontainers.image.licenses="GPLv3"

ENV PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    TYPE=PAPER \
    VERSION=latest \
    MEMORY=1G \
    RCON_ENABLED=true \
    RCON_PORT=25575 \
    DATA_DIR=/data

RUN <<EOF
set -e
apt-get update

# Install download tools
apt-get install -y --no-install-recommends wget ca-certificates tar

# Create non-root user
groupadd -g 1000 minecraft
useradd -u 1000 -g minecraft -m -s /bin/bash minecraft

# Normalize architecture strings across different vendors
ARCH=$(dpkg --print-architecture)
if [ "$ARCH" = "amd64" ]; then JAVA_ARCH="x64"; ZULU_ARCH="x86";
elif [ "$ARCH" = "arm64" ]; then JAVA_ARCH="aarch64"; ZULU_ARCH="arm";
else echo "Unsupported architecture: $ARCH"; exit 1; fi

# Resolve the download URL based on the requested flavor
case "$JAVA_FLAVOR" in
    "temurin")
        URL="https://api.adoptium.net/v3/binary/latest/${JAVA_VERSION}/ga/linux/${JAVA_ARCH}/jdk/hotspot/normal/eclipse"
        ;;
    "corretto")
        URL="https://corretto.aws/downloads/latest/amazon-corretto-${JAVA_VERSION}-${JAVA_ARCH}-linux-jdk.tar.gz"
        ;;
    "microsoft")
        URL="https://aka.ms/download-jdk/microsoft-jdk-${JAVA_VERSION}-linux-${JAVA_ARCH}.tar.gz"
        ;;
    "azul")
        API_URL="https://api.azul.com/zulu/download/community/v1.0/bundles/latest/?os=linux&arch=${ZULU_ARCH}&hw_bitness=64&ext=tar.gz&jdk_version=${JAVA_VERSION}&bundle_type=jdk"
        URL=$(wget -qO- "$API_URL" | python3 -c "import sys, json; print(json.load(sys.stdin)['url'])")
        ;;
    "graalvm")
        URL="https://download.oracle.com/graalvm/${JAVA_VERSION}/latest/graalvm-jdk-${JAVA_VERSION}_linux-${JAVA_ARCH}_bin.tar.gz"
        ;;
    *)
        echo "Unsupported Java flavor: $JAVA_FLAVOR"
        exit 1
        ;;
esac

if [ -z "$URL" ]; then echo "Failed to resolve Java download URL"; exit 1; fi

# Download and extract Java uniformly
mkdir -p /opt/java
wget -q -O /tmp/java.tar.gz "$URL"
tar -xzf /tmp/java.tar.gz -C /opt/java --strip-components=1

# Symlink Java binaries to system PATH
ln -s /opt/java/bin/* /usr/local/bin/

# Cleanup temporary files and download tools to shrink image
rm /tmp/java.tar.gz
apt-get purge -y --auto-remove wget
rm -rf /var/lib/apt/lists/*
EOF

COPY --from=builder /opt/venv /opt/venv

WORKDIR /data
RUN mkdir -p templates runtime && chown -R minecraft:minecraft /data

USER minecraft:minecraft

VOLUME ["/data/templates", "/data/runtime"]
EXPOSE 25565 25575

ENTRYPOINT ["/opt/venv/bin/python", "-m", "orchestrator"]