"""WiFi scanning via `netsh` on Windows.

The English-header parsing path was verified against a live
`netsh wlan show networks mode=bssid` capture on a real Windows 11 machine.
The Polish-header path is inferred from community-reported `netsh` output
and standard Windows networking terminology -- it has NOT been verified
against a live Polish-locale system, and is flagged at each such spot below.
"""

from __future__ import annotations

import logging
import platform
import re
from datetime import datetime, timezone

from .base import ScanParseError, WifiScanner
from .models import NetworkInfo, canonical_band, frequency_mhz_from_channel, normalize_security

logger = logging.getLogger(__name__)

# SSID/BSSID acronyms are assumed to stay untranslated under Polish locale
# (consistent with community reports) -- unverified live.
_SSID_HEADER = re.compile(r"^SSID\s+\d+\s*:\s?(.*)$")
_BSSID_HEADER = re.compile(r"^\s*BSSID\s+\d+\s*:\s*([0-9A-Fa-f:]{17})")
_AUTH = re.compile(r"^\s*(?:Authentication|Uwierzytelnianie)\s*:\s*(.+?)\s*$")
_SIGNAL = re.compile(r"^\s*(?:Signal|Sygnał)\s*:\s*(\d+)\s*%")
_BAND = re.compile(r"^\s*(?:Band|Pasmo)\s*:\s*(.+?)\s*$")
_CHANNEL = re.compile(r"^\s*(?:Channel|Kanał)\s*:\s*(\d+)")
# "There are N networks currently visible." -- Polish wording unverified.
_NETWORK_COUNT = re.compile(r"There are (\d+) networks? currently visible", re.IGNORECASE)


class _PendingBlock:
    """Accumulates fields for one BSSID block until the next boundary."""

    def __init__(self) -> None:
        self.bssid: str | None = None
        self.signal_percent: int | None = None
        self.band_raw: str | None = None
        self.channel: int | None = None

    def is_complete(self) -> bool:
        return None not in (self.bssid, self.signal_percent, self.band_raw, self.channel)

    def is_empty(self) -> bool:
        return self.bssid is None and self.signal_percent is None and self.band_raw is None and self.channel is None


class WindowsWifiScanner(WifiScanner):
    """Scans for WiFi networks using `netsh wlan show networks mode=bssid`."""

    TOOL_NAME = "netsh"

    def scan(self) -> list[NetworkInfo]:
        # netsh emits console-OEM-codepage bytes, not UTF-8: on a Polish
        # system, header words containing special characters (e.g. "Sygnal"
        # with an l-stroke, "Kanal") would silently mis-decode -- and every
        # regex above would simply fail to match -- under the wrong codepage.
        # "oem" is a Windows-only codec alias for the console's codepage, so
        # it is only used when actually running on Windows; the parsing logic
        # itself works on any decoded text, so it stays testable elsewhere.
        encoding = "oem" if platform.system() == "Windows" else "utf-8"
        output = self._run_command(
            ["netsh", "wlan", "show", "networks", "mode=bssid"],
            timeout=10.0,
            encoding=encoding,
        )
        if output is None:
            return []

        return self._parse(output)

    def _parse(self, text: str) -> list[NetworkInfo]:
        """Parse `netsh` output via a key-driven line-by-line state machine.

        Two structural facts rule out simpler approaches (fixed line counts
        or indentation-depth arithmetic): a single SSID can have multiple
        `BSSID N :` sub-blocks (each a distinct access point sharing the
        parent SSID/Authentication), and blocks vary in which optional
        sub-lines are present (e.g. a "Bss Load:" section is sometimes
        entirely absent). So instead of counting lines, we react only to
        recognized `key : value` lines and ignore everything else (Network
        type, Encryption, Radio type, Bss Load and its nested lines, QoS
        fields, rate lists) by falling through unmatched.
        """
        scan_time = datetime.now(timezone.utc)
        results: list[NetworkInfo] = []

        current_ssid: str | None = None
        current_auth_raw: str = ""
        block = _PendingBlock()
        reported_count: int | None = None

        def flush() -> None:
            nonlocal block
            if block.is_empty():
                return
            if not block.is_complete() or current_ssid is None:
                logger.warning(
                    "skipping incomplete BSSID block for SSID %r: bssid=%s signal=%s band=%s channel=%s",
                    current_ssid, block.bssid, block.signal_percent, block.band_raw, block.channel,
                )
                block = _PendingBlock()
                return

            assert block.bssid is not None
            assert block.channel is not None
            assert block.band_raw is not None
            assert block.signal_percent is not None

            frequency_mhz = frequency_mhz_from_channel(block.channel, block.band_raw)
            if frequency_mhz is None:
                logger.warning(
                    "skipping BSSID %s: unrecognized band %r for channel %d",
                    block.bssid, block.band_raw, block.channel,
                )
                block = _PendingBlock()
                return

            results.append(
                NetworkInfo(
                    ssid=current_ssid,
                    bssid=block.bssid.lower(),
                    channel=block.channel,
                    frequency_mhz=frequency_mhz,
                    band=canonical_band(block.band_raw),
                    signal_dbm=None,
                    signal_percent=block.signal_percent,
                    security=normalize_security(current_auth_raw),
                    timestamp=scan_time,
                )
            )
            block = _PendingBlock()

        for line in text.splitlines():
            if reported_count is None:
                count_match = _NETWORK_COUNT.search(line)
                if count_match:
                    reported_count = int(count_match.group(1))

            ssid_match = _SSID_HEADER.match(line)
            if ssid_match:
                flush()
                current_ssid = ssid_match.group(1)
                current_auth_raw = ""
                continue

            bssid_match = _BSSID_HEADER.match(line)
            if bssid_match:
                flush()
                block.bssid = bssid_match.group(1)
                continue

            auth_match = _AUTH.match(line)
            if auth_match:
                current_auth_raw = auth_match.group(1)
                continue

            signal_match = _SIGNAL.match(line)
            if signal_match:
                block.signal_percent = int(signal_match.group(1))
                continue

            band_match = _BAND.match(line)
            if band_match:
                block.band_raw = band_match.group(1)
                continue

            channel_match = _CHANNEL.match(line)
            if channel_match:
                block.channel = int(channel_match.group(1))
                continue

        flush()

        if reported_count is not None and reported_count > 0 and not results:
            raise ScanParseError(
                f"netsh reported {reported_count} network(s) but none could be parsed -- "
                "the header-parsing regexes may be stale for this netsh version/locale"
            )

        if not results:
            logger.warning("netsh reported 0 networks in range")

        return results
