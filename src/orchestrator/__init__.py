from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("minecraft-server")
except PackageNotFoundError:  # running from a source checkout without installing
    __version__ = "0.0.0+unknown"
