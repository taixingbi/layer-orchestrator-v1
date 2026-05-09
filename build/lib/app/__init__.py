"""Application package (logging, future modules)."""

import os
from importlib.metadata import PackageNotFoundError, version as package_version


def _fallback_package_version() -> str:
    """Package metadata fallback when APP_VERSION is not provided."""
    try:
        return package_version("layer-orchestrator-v1")
    except PackageNotFoundError:
        return "dev"


__version__ = os.getenv("APP_VERSION") or _fallback_package_version()
