"""Picks the right WifiScanner implementation for the running OS."""

from __future__ import annotations

import platform

from .base import UnsupportedPlatformError, WifiScanner
from .linux_scanner import LinuxWifiScanner
from .windows_scanner import WindowsWifiScanner


def get_scanner() -> WifiScanner:
    """Return a `WifiScanner` for the current operating system.

    Raises `UnsupportedPlatformError` for any OS without an implementation
    (e.g. macOS is intentionally out of scope for this phase).
    """
    system = platform.system()
    if system == "Windows":
        return WindowsWifiScanner()
    if system == "Linux":
        return LinuxWifiScanner()
    raise UnsupportedPlatformError(
        f"airmap does not support WiFi scanning on {system!r} yet "
        "(only Windows via netsh and Linux via nmcli are implemented in this phase)."
    )
