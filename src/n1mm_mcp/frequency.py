"""Frequency normalization for N1MM UDP messages.

N1MM uses two different frequency formats:
  - RadioInfo/ContactInfo: tens of Hz as integer (1407400 = 14.0740 MHz)
  - Spot: MHz as float string ("14.195" = 14.1950 MHz)

All tool output normalizes to MHz with 4 decimal places.
"""

from __future__ import annotations

# Band edges in MHz for HF + 6m
_BAND_EDGES: list[tuple[float, float, str]] = [
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


def from_mhz_str(val: str) -> float:
    """Convert N1MM MHz string (from Spot) to float.

    "14.195" → 14.1950
    """
    try:
        return round(float(val), 4)
    except (ValueError, TypeError):
        return 0.0


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
