"""CLI runner: `python -m airmap.main`."""

from __future__ import annotations

import logging
import platform
import sys

from .base import ScanParseError, UnsupportedPlatformError
from .factory import get_scanner
from .models import NetworkInfo

_COLUMN_WIDTHS = (32, 7, 8, 8, 10)
_HEADERS = ("SSID", "Channel", "Band", "Signal", "Security")


def _format_signal(network: NetworkInfo) -> str:
    if network.signal_percent is not None:
        return f"{network.signal_percent}%"
    if network.signal_dbm is not None:
        return f"{network.signal_dbm}dBm"
    return "?"


def _print_table(networks: list[NetworkInfo]) -> None:
    row_format = "  ".join(f"{{:<{width}}}" for width in _COLUMN_WIDTHS)
    print(row_format.format(*_HEADERS))
    print(row_format.format(*("-" * width for width in _COLUMN_WIDTHS)))
    for network in sorted(networks, key=lambda n: (n.ssid.lower(), n.bssid)):
        ssid_display = (network.ssid or "<hidden>")[: _COLUMN_WIDTHS[0]]
        print(
            row_format.format(
                ssid_display,
                network.channel,
                network.band,
                _format_signal(network),
                network.security,
            )
        )


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s:%(name)s:%(message)s")

    try:
        scanner = get_scanner()
    except UnsupportedPlatformError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if not scanner.is_available():
        print(
            f"Error: required tool for {platform.system()} not found on PATH.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        networks = scanner.scan()
    except ScanParseError as exc:
        print(f"Error: could not parse scan output: {exc}", file=sys.stderr)
        sys.exit(1)

    if not networks:
        print("No WiFi networks found (0 in range, or scan failed -- see warnings above).")
        return

    _print_table(networks)


if __name__ == "__main__":
    main()
