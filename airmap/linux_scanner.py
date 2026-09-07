"""WiFi scanning via `nmcli` (NetworkManager CLI) on Linux.

NOT verified against a live system -- implemented strictly from nmcli's
documented `--terse` output format (no Linux machine was available when this
module was written). Review the parsing carefully against a real `nmcli`
before relying on it in production.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from .base import ScanParseError, WifiScanner
from .models import NetworkInfo, band_from_frequency_mhz, normalize_security

logger = logging.getLogger(__name__)

_FIELDS = ("SSID", "BSSID", "CHAN", "FREQ", "SIGNAL", "SECURITY")
_FREQ_DIGITS = re.compile(r"\d+")


def _split_terse_line(line: str) -> list[str]:
    """Split one `nmcli --terse` line into fields, honoring its escaping.

    nmcli's terse mode separates fields with `:`, but a field's own value can
    contain a literal `:` (BSSID is a MAC address, e.g. `aa:bb:cc:dd:ee:ff`),
    which nmcli escapes as `\\:`; a literal `\\` is escaped as `\\\\`.

    A regex negative-lookbehind split (`re.split(r'(?<!\\\\):', line)`) looks
    like an easy way to do this but has a real bug: it only inspects the one
    character immediately before a `:`, so it cannot distinguish an *even*
    run of backslashes (a literal trailing `\\` followed by a real delimiter)
    from an *odd* run (an escaped colon) -- the classic ad-hoc-escaping edge
    case. A manual single-pass scan does splitting and unescaping together
    and handles this correctly regardless of how many backslashes precede a
    colon.
    """
    fields: list[str] = []
    current: list[str] = []
    i = 0
    length = len(line)
    while i < length:
        char = line[i]
        if char == "\\" and i + 1 < length and line[i + 1] in (":", "\\"):
            current.append(line[i + 1])
            i += 2
            continue
        if char == ":":
            fields.append("".join(current))
            current = []
            i += 1
            continue
        current.append(char)
        i += 1
    fields.append("".join(current))
    return fields


class LinuxWifiScanner(WifiScanner):
    """Scans for WiFi networks using `nmcli`."""

    TOOL_NAME = "nmcli"

    def scan(self) -> list[NetworkInfo]:
        output = self._run_command(
            ["nmcli", "--terse", "--fields", ",".join(_FIELDS), "dev", "wifi", "list"],
            timeout=10.0,
        )
        if output is None:
            return []

        lines = [line for line in output.splitlines() if line.strip()]
        if not lines:
            logger.warning("nmcli reported 0 networks in range")
            return []

        scan_time = datetime.now(timezone.utc)
        results: list[NetworkInfo] = []
        malformed = 0

        for line in lines:
            fields = _split_terse_line(line)
            if len(fields) != len(_FIELDS):
                logger.warning(
                    "skipping malformed nmcli line (expected %d fields, got %d): %r",
                    len(_FIELDS),
                    len(fields),
                    line,
                )
                malformed += 1
                continue

            ssid, bssid, chan_raw, freq_raw, signal_raw, security_raw = fields

            freq_match = _FREQ_DIGITS.search(freq_raw)
            if not freq_match:
                logger.warning("skipping line with unparsable FREQ %r: %r", freq_raw, line)
                malformed += 1
                continue
            frequency_mhz = int(freq_match.group())

            try:
                channel = int(chan_raw)
                signal_percent = int(signal_raw)
            except ValueError:
                logger.warning("skipping line with non-numeric CHAN/SIGNAL: %r", line)
                malformed += 1
                continue

            results.append(
                NetworkInfo(
                    ssid=ssid,
                    bssid=bssid.lower(),
                    channel=channel,
                    frequency_mhz=frequency_mhz,
                    band=band_from_frequency_mhz(frequency_mhz),
                    signal_dbm=None,
                    signal_percent=signal_percent,
                    security=normalize_security(security_raw),
                    timestamp=scan_time,
                )
            )

        if not results and malformed == len(lines):
            raise ScanParseError(
                f"all {len(lines)} nmcli output line(s) failed to parse -- "
                "the nmcli version's --terse format may have changed"
            )

        return results
