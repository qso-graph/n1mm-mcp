"""Frequency normalization for N1MM UDP messages.

N1MM uses two different frequency formats:
  - RadioInfo/ContactInfo: tens of Hz as integer (1407400 = 14.0740 MHz)
  - Spot: kHz as float string ("14195.0" = 14.1950 MHz)

All tool output normalizes to MHz with 4 decimal places.
"""

from __future__ import annotations

# Band edges in MHz, 2200 m through 6 m. 2200 m and 630 m are the ITU
# allocations (135.7-137.8 kHz, 472-479 kHz).
_BAND_EDGES: list[tuple[float, float, str]] = [
    (0.1357, 0.1378, "2200m"),
    (0.472, 0.479, "630m"),
    (1.800, 2.000, "160m"),
    (3.500, 4.000, "80m"),
    (5.330, 5.410, "60m"),
    (7.000, 7.300, "40m"),
    (10.100, 10.150, "30m"),
    (14.000, 14.350, "20m"),
    (18.068, 18.168, "17m"),
    (21.000, 21.450, "15m"),
    (24.890, 24.990, "12m"),
    (28.000, 29.700, "10m"),
    (50.000, 54.000, "6m"),
]


def from_tens_hz(val: int) -> float:
    """Convert N1MM tens-of-Hz integer to MHz.

    1407400 → 14.0740
    712345  → 7.1235 (truncated to 4 decimal places)
    0       → 0.0
    """
    if val == 0:
        return 0.0
    return round(val / 100000.0, 4)


def from_spot_freq(val: str) -> float:
    """Convert N1MM Spot frequency string to MHz.

    N1MM's spot frequency is always kHz: the documented example is
    <frequency>7061.2</frequency>, and real packets carry "14195.0".
    The unit is never guessed from the size, which read a 630 m spot
    ("475.0") as 475 MHz and a 2200 m spot ("137.5") as 137.5 MHz.
    https://n1mmwp.hamdocs.com/appendices/external-udp-broadcasts/

    "14195.0" → 14.1950
    "475.0"   → 0.4750
    """
    try:
        freq = float(val)
    except (ValueError, TypeError):
        return 0.0
    if freq <= 0.0:
        return 0.0
    return round(freq / 1000.0, 4)


def freq_to_band(freq_mhz: float) -> str:
    """Determine amateur band from frequency in MHz.

    Returns band name (e.g., "20m") or "unknown".
    """
    if freq_mhz <= 0.0:
        return "unknown"
    for low, high, name in _BAND_EDGES:
        if low <= freq_mhz <= high:
            return name
    return "unknown"
