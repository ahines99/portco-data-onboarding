"""Locate immutable runtime assets in a checkout or an installed wheel."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
CHECKOUT_ROOT = PACKAGE_ROOT.parent
PACKAGED_RESOURCES = PACKAGE_ROOT / "_resources"
RESOURCE_ROOT = PACKAGED_RESOURCES if PACKAGED_RESOURCES.is_dir() else CHECKOUT_ROOT
IN_CHECKOUT = not PACKAGED_RESOURCES.is_dir()


def default_var_root() -> Path:
    """Installed applications write to the working directory, never site-packages."""
    return (CHECKOUT_ROOT if IN_CHECKOUT else Path.cwd()) / "var"
