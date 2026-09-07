"""Shared data model for scanned WiFi networks.

Both scanner implementations produce ``NetworkInfo`` records. The
normalization helpers here (security label, band/frequency conversion) live
in this module -- not in either scanner -- because they encode rules about
*our* data model (what counts as "WPA2", how a channel maps to a frequency),
not anything specific to nmcli or netsh. Keeping them here means both
scanners share one answer to "why is WPA1+WPA2 reported as WPA2" instead of
each having their own (possibly diverging) copy.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class NetworkInfo:
    """A single access point observed during one scan.

    Fields the underlying OS tool does not provide are ``None`` -- never a
    guessed or derived stand-in -- except for `frequency_mhz`/`band`, which
    are legitimately derivable from each other (see `band_from_frequency_mhz`
    and `frequency_mhz_from_channel`) and are not considered "guesses".
    """

    ssid: str
    bssid: str
    channel: int
    frequency_mhz: int
    band: str
    signal_dbm: int | None
    signal_percent: int | None
    security: str
    timestamp: datetime


def normalize_security(raw: str) -> str:
    """Map a raw security/authentication string to one of our 4 labels.

    Both `nmcli`'s SECURITY column (e.g. "WPA1 WPA2", "--", "WEP") and
    `netsh`'s Authentication field (e.g. "WPA2-Personal", "Open") funnel
    through this one function so both platforms agree on what "WPA2" means.

    Priority is "strongest wins": if an AP advertises multiple standards at
    once (a transitional/mixed-mode AP, e.g. "WPA1 WPA2"), we report the
    strongest one actually available to an up-to-date client, since that is
    what a modern client will negotiate. WEP and WPA1-only do not map to
    "Open" (that would understate the risk) or "WPA2" (that would overstate
    it) -- "Unknown" is the honest bucket for anything that isn't cleanly
    WPA2/WPA3/Open.
    """
    value = raw.strip().upper()
    if "WPA3" in value:
        return "WPA3"
    if "WPA2" in value:
        return "WPA2"
    if value in ("", "--", "OPEN", "NONE"):
        return "Open"
    return "Unknown"


def band_from_frequency_mhz(freq_mhz: int) -> str:
    """Derive the band label from a real frequency reading (Linux direction).

    `nmcli` reports true frequency in MHz, so band is the derived value here
    (the opposite direction from Windows, where band is native and frequency
    is derived -- see `frequency_mhz_from_channel`). Boundaries follow the
    standard WiFi allocations; anything outside them returns "Unknown"
    rather than raising or inventing a label.
    """
    if 2400 <= freq_mhz <= 2500:
        return "2.4GHz"
    if 5000 <= freq_mhz <= 5895:
        return "5GHz"
    if 5925 <= freq_mhz <= 7125:
        return "6GHz"
    return "Unknown"


def frequency_mhz_from_channel(channel: int, band_raw: str) -> int | None:
    """Derive frequency in MHz from (channel, band) -- the Windows direction.

    `netsh` never exposes raw frequency, only a textual Band ("2.4 GHz" /
    "5 GHz" / "6 GHz") and a Channel number, so frequency must be computed.
    Channel 14 in the 2.4GHz band is a documented off-grid exception
    (2484 MHz, used in Japan) that does not fit the regular 5 MHz spacing
    formula and must be hardcoded. Returns None -- not a guess -- when the
    band string is unrecognized, so the caller can skip that one record
    instead of fabricating a frequency.
    """
    band = band_raw.strip().replace(",", ".").replace(" ", "").upper()
    if band in ("2.4GHZ", "2,4GHZ"):
        if channel == 14:
            return 2484
        return 2407 + 5 * channel
    if band == "5GHZ":
        return 5000 + 5 * channel
    if band == "6GHZ":
        return 5950 + 5 * channel
    return None


def canonical_band(band_raw: str) -> str:
    """Normalize a raw Windows Band string to our canonical band label.

    Handles the documented (but unverified on a live Polish system) risk
    that a Polish-locale `netsh` might render band values with a comma
    decimal separator (e.g. "2,4 GHz" instead of "2.4 GHz").
    """
    band = band_raw.strip().replace(",", ".").replace(" ", "").upper()
    if band == "2.4GHZ":
        return "2.4GHz"
    if band == "5GHZ":
        return "5GHz"
    if band == "6GHZ":
        return "6GHz"
    return "Unknown"
