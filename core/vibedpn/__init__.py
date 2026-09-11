"""VibeDPN core package: configuration model, router engine, API and CLI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("vibedpn")
except PackageNotFoundError:  # source tree without an installed distribution
    __version__ = "0.0.0"

__all__ = ["__version__"]
