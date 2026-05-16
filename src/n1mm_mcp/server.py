"""n1mm-mcp — MCP server for N1MM Logger+ contest state.

Phase 1 tools (8 of 12 composite State Views):
  n1mm_current_state, n1mm_lookup, n1mm_contacts, n1mm_bandmap,
  n1mm_performance, n1mm_multipliers, n1mm_clock, n1mm_diagnostics
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from fastmcp import FastMCP

from . import __spec_version__, __version__
from .frequency import freq_to_band, from_spot_freq, from_tens_hz
from .state import (
    DEFAULT_HEARTBEAT_TIMEOUT,
    DEFAULT_MAX_SPOTS,
    DEFAULT_SPOT_TTL,
    DEFAULT_STALE_TIMEOUT,
    StateEngine,
)

mcp = FastMCP(
    "n1mm-mcp",
    version=__version__,
    instructions=(
        "N1MM Logger+ MCP server — live contest state via UDP broadcast. "
        "Tools return composite snapshots of contest state. "
        "All tools accept optional station_name for multi-station setups."
    ),
)

# Global state — initialized in main()
_state: StateEngine | None = None


def _get_state() -> StateEngine:
    global _state
    if _state is None:
        _state = StateEngine()
    return _state


def _station_error(names: list[str]) -> dict[str, Any]:
    """Error for ambiguous station_name (Einstein MANDATORY #2)."""
    return {
        "error": "multiple_stations",
        "stations": names,
        "message": "Multiple stations detected. Specify station_name parameter.",
    }


def _disconnected_error() -> dict[str, Any]:
    return {"status": "disconnected", "message": "No N1MM data received yet."}


def _radio_to_dict(radio) -> dict[str, Any]:
    freq = from_tens_hz(radio.freq_hz)
    return {
        "radio_nr": radio.radio_nr,
        "frequency_mhz": freq,
        "band": freq_to_band(freq),
        "mode": radio.mode,
        "is_running": radio.is_running,
        "is_split": radio.is_split,
        "is_transmitting": radio.is_transmitting,
        "is_connected": radio.is_connected,
        "antenna": radio.antenna,
        "aux_antenna": radio.aux_antenna,
        "aux_antenna_name": radio.aux_antenna_name,
        "rotors": radio.rotors,
        "radio_name": radio.radio_name,
        "active_radio_nr": radio.active_radio_nr,
    }


# ---------------------------------------------------------------------------
# Tool 0: get_version_info — Fleet Identity Attestation
# ---------------------------------------------------------------------------


def _version_info_payload() -> dict[str, Any]:
    """Build the version info envelope. Pulled into a helper so tests can
    call it directly without going through the FastMCP wrapper.

    This is the only tool that doesn't touch the UDP listener state —
    useful as an operator self-check when N1MM isn't broadcasting.
    """
    return {
        "service_name": "n1mm-mcp",
        "service_version": __version__,
        "spec_version": __spec_version__,
    }


@mcp.tool()
def get_version_info() -> dict[str, Any]:
    """Get n1mm-mcp service version and upstream UDP contract version.

    Returns the running PyPI version of n1mm-mcp and the N1MM Logger+
    UDP broadcast contract revision in use. Use this to confirm fleet
    alignment across MCP deployments — agents can compare service_version
    and spec_version across servers to detect drift without going outside
    the MCP protocol.

    Note: n1mm_diagnostics remains the canonical health probe (heartbeat,
    parse errors, memory). get_version_info is a lighter-weight identity
    attestation that succeeds even when N1MM isn't broadcasting.

    Returns:
        service_name, service_version (PyPI), and spec_version (UDP contract).
    """
    return _version_info_payload()


# ---------------------------------------------------------------------------
# Tool 1: n1mm_current_state — Station Snapshot
# ---------------------------------------------------------------------------
@mcp.tool()
def n1mm_current_state(station_name: str | None = None) -> dict[str, Any]:
    """Complete station snapshot — connection, contest, operator, radios.

    Returns connection status, contest info, operator callsign, and full
    radio state for Radio 1 (and Radio 2 if SO2R). This is the first tool
    any AI session should call.
    """
    state = _get_state()
    station = state.resolve_station(station_name)
    if station is None:
        names = state.get_station_names()
        if not names:
            return _disconnected_error()
        return _station_error(names)

    with station.radio_lock:
        result: dict[str, Any] = {
            "connection": {
                "status": state.connection_status(),
                "last_packet": (
                    state.last_packet_at.isoformat() if state.last_packet_at else None
                ),
                "uptime_seconds": (
                    datetime.now(timezone.utc) - state.started_at
                ).total_seconds(),
                "packets_received": state.packets_received,
            },
            "station": {
                "contest_name": station.station_info.contest_name,
                "mycall": station.station_info.mycall,
                "station_name": station.station_name,
                "dbname": station.station_info.dbname,
            },
        }

        # Operator from most recent RadioInfo
        radios = station.radio_state
        if radios:
            first_radio = next(iter(radios.values()))
            result["operator"] = {
                "op_call": first_radio.op_call,
                "mycall": first_radio.mycall,
            }
        else:
            result["operator"] = {"op_call": "", "mycall": station.station_info.mycall}

        # Radio state
        for nr in sorted(radios.keys()):
            result[f"radio_{nr}"] = _radio_to_dict(radios[nr])

    return result


# ---------------------------------------------------------------------------
# Tool 2: n1mm_lookup — Pre-Log Callsign (Contest-Copilot Trigger)
# ---------------------------------------------------------------------------
@mcp.tool()
def n1mm_lookup(station_name: str | None = None) -> dict[str, Any]:
    """Pre-log callsign lookup — THE Contest-Copilot trigger.

    Fires when operator types a callsign and presses spacebar in N1MM.
    Returns the lookup data plus current band/mode from RadioInfo.
    Check lookup_age_ms — if >30000, the advice window has closed.
    """
    state = _get_state()
    station = state.resolve_station(station_name)
    if station is None:
        names = state.get_station_names()
        if not names:
            return _disconnected_error()
        return _station_error(names)

    with station.lookup_lock:
        lookup = station.lookup_state
        if lookup is None:
            return {"status": "no_lookup", "message": "No callsign lookup received yet."}

        age_ms = int(
            (datetime.now(timezone.utc) - lookup.received_at).total_seconds() * 1000
        )

    # Get current band/mode from RadioInfo (Einstein: prevents cascading calls)
    current_band = "unknown"
    current_mode = ""
    with station.radio_lock:
        radios = station.radio_state
        if radios:
            # Use active radio
            active_nr = next(iter(radios.values())).active_radio_nr
            active = radios.get(active_nr, next(iter(radios.values())))
            freq = from_tens_hz(active.freq_hz)
            current_band = freq_to_band(freq)
            current_mode = active.mode

    return {
        "call": lookup.call,
        "gridsquare": lookup.gridsquare,
        "name": lookup.name,
        "section": lookup.section,
        "country_prefix": lookup.country_prefix,
        "continent": lookup.continent,
        "zone": lookup.zone,
        "is_multiplier1": lookup.is_multiplier1,
        "is_multiplier2": lookup.is_multiplier2,
        "is_multiplier3": lookup.is_multiplier3,
        "lookup_age_ms": age_ms,
        "current_band": current_band,
        "current_mode": current_mode,
    }


# ---------------------------------------------------------------------------
# Tool 3: n1mm_contacts — QSO Log & History
# ---------------------------------------------------------------------------
@mcp.tool()
def n1mm_contacts(
    count: int = 10,
    since: str | None = None,
    band: str | None = None,
    mode: str | None = None,
    call_pattern: str | None = None,
    station_name: str | None = None,
) -> dict[str, Any]:
    """QSO log — recent contacts, edits, and deletes.

    Returns the last QSO, filtered recent QSOs, recent edits, and recent
    deletes in one coherent snapshot.

    Args:
        count: Number of recent QSOs to return (default 10, max 100).
        since: ISO timestamp — return only QSOs after this time.
        band: Filter by band (e.g., "20m").
        mode: Filter by mode (e.g., "CW").
        call_pattern: Filter by callsign prefix.
        station_name: Station to query (auto-detected if only one).
    """
    state = _get_state()
    station = state.resolve_station(station_name)
    if station is None:
        names = state.get_station_names()
        if not names:
            return _disconnected_error()
        return _station_error(names)

    count = min(max(count, 1), 100)

    with station.contact_lock:
        log = station.contact_log
        total = len(log)

        # Filter
        filtered = log
        if since:
            filtered = [c for c in filtered if c.timestamp >= since]
        if band:
            filtered = [
                c for c in filtered if freq_to_band(from_tens_hz(c.rxfreq)) == band
            ]
        if mode:
            filtered = [c for c in filtered if c.mode.upper() == mode.upper()]
        if call_pattern:
            pat = call_pattern.upper()
            filtered = [c for c in filtered if c.call.upper().startswith(pat)]

        recent = filtered[-count:][::-1]  # newest first

        last_qso = None
        if log:
            c = log[-1]
            freq = from_tens_hz(c.rxfreq)
            last_qso = {
                "call": c.call,
                "band": freq_to_band(freq),
                "frequency_mhz": freq,
                "mode": c.mode,
                "timestamp": c.timestamp,
                "points": c.points,
                "is_multiplier1": c.is_multiplier1,
                "is_run_qso": c.is_run_qso,
                "operator": c.operator,
                "guid": c.guid,
            }

        qso_list = []
        for c in recent:
            freq = from_tens_hz(c.rxfreq)
            qso_list.append(
                {
                    "call": c.call,
                    "band": freq_to_band(freq),
                    "frequency_mhz": freq,
                    "mode": c.mode,
                    "timestamp": c.timestamp,
                    "points": c.points,
                    "continent": c.continent,
                    "country_prefix": c.country_prefix,
                    "is_multiplier1": c.is_multiplier1,
                    "is_run_qso": c.is_run_qso,
                    "guid": c.guid,
                }
            )

        edits = [
            {
                "call": e.call,
                "old_call": e.old_call,
                "old_timestamp": e.old_timestamp,
                "timestamp": e.timestamp,
                "guid": e.guid,
            }
            for e in station.edit_log
        ]

        deletes = list(station.delete_log)

    result: dict[str, Any] = {
        "total_qsos": total,
        "last_qso": last_qso,
        "recent_qsos": qso_list,
        "recent_edits": edits[-10:],
        "recent_deletes": deletes[-10:],
    }

    # Cross-reference Score XML — surface discrepancy if QSOs were logged
    # before the MCP server started (UDP-only limitation)
    with station.score_lock:
        if station.score_state:
            score_qsos = sum(station.score_state.band_mode_qsos.values())
            if score_qsos > total:
                result["score_discrepancy"] = {
                    "score_xml_qsos": score_qsos,
                    "observed_qsos": total,
                    "missed": score_qsos - total,
                    "reason": (
                        "QSOs were logged before the MCP server started. "
                        "Score XML reports cumulative totals but individual "
                        "contact details are only available for QSOs observed live."
                    ),
                }

    return result


# ---------------------------------------------------------------------------
# Tool 4: n1mm_bandmap — Live Spots & Mult Targets
# ---------------------------------------------------------------------------
@mcp.tool()
def n1mm_bandmap(
    band: str | None = None,
    mode: str | None = None,
    callsign: str | None = None,
    mults_only: bool = False,
    station_name: str | None = None,
) -> dict[str, Any]:
    """Live bandmap — spots, mult targets, and activity summary.

    Returns active spots (with TTL eviction), unworked multipliers,
    and per-band spot activity counts in one snapshot.

    Args:
        band: Filter by band (e.g., "20m").
        mode: Filter by mode.
        callsign: Search by callsign prefix.
        mults_only: If true, only return spots flagged as multipliers.
        station_name: Station to query.
    """
    state = _get_state()
    station = state.resolve_station(station_name)
    if station is None:
        names = state.get_station_names()
        if not names:
            return _disconnected_error()
        return _station_error(names)

    with station.spot_lock:
        spots = list(station.spot_map.values())
        map_size = len(station.spot_map)

    now = datetime.now(timezone.utc)

    # Filter
    filtered = spots
    if band:
        filtered = [s for s in filtered if freq_to_band(from_spot_freq(s.frequency)) == band]
    if mode:
        filtered = [s for s in filtered if s.mode.upper() == mode.upper()]
    if callsign:
        pat = callsign.upper()
        filtered = [s for s in filtered if s.dxcall.upper().startswith(pat)]
    if mults_only:
        filtered = [s for s in filtered if "mult" in s.status_list.lower()]

    spot_list = []
    for s in filtered:
        age_s = (now - s.received_at).total_seconds()
        spot_list.append(
            {
                "dxcall": s.dxcall,
                "frequency_mhz": from_spot_freq(s.frequency),
                "band": freq_to_band(from_spot_freq(s.frequency)),
                "mode": s.mode,
                "spotter": s.spotter_call,
                "status": s.status,
                "status_list": s.status_list,
                "comment": s.comment,
                "age_seconds": int(age_s),
            }
        )

    # Sort by frequency
    spot_list.sort(key=lambda x: x["frequency_mhz"])

    # Band activity from recent spots
    band_activity: dict[str, int] = {}
    with station.spot_lock:
        for s in station.spot_buffer:
            if (now - s.received_at).total_seconds() < 1800:  # 30 min window
                b = freq_to_band(from_spot_freq(s.frequency))
                band_activity[b] = band_activity.get(b, 0) + 1

    return {
        "spots": spot_list,
        "spot_count": len(spot_list),
        "spot_map_size": map_size,
        "band_activity": band_activity,
    }


# ---------------------------------------------------------------------------
# Tool 5: n1mm_performance — Rate, Bands & Strategy
# ---------------------------------------------------------------------------
@mcp.tool()
def n1mm_performance(
    band: str | None = None,
    mode: str | None = None,
    station_name: str | None = None,
) -> dict[str, Any]:
    """Complete performance snapshot — score, rate, bands, run/S&P, timeline.

    Returns score, rolling rates (10m/30m/60m), rate derivative for band
    exhaustion detection, per-band breakdown, per-mode breakdown, hourly
    summary, and run vs S&P stats in one coherent view.

    Args:
        band: Filter rate/breakdown to specific band.
        mode: Filter to specific mode.
        station_name: Station to query.
    """
    state = _get_state()
    station = state.resolve_station(station_name)
    if station is None:
        names = state.get_station_names()
        if not names:
            return _disconnected_error()
        return _station_error(names)

    now = datetime.now(timezone.utc)

    # Score
    score_data: dict[str, Any] = {"total_qsos": 0, "total_score": 0}
    with station.score_lock:
        if station.score_state:
            s = station.score_state
            score_data = {
                "total_qsos": sum(s.band_mode_qsos.values()),
                "total_score": s.score,
                "band_mode_qsos": {
                    f"{b}_{m}": c for (b, m), c in s.band_mode_qsos.items()
                },
            }

    with station.contact_lock:
        log = station.contact_log
        total = len(log)

        # Filter for rate calculation
        filtered = log
        if band:
            filtered = [
                c for c in filtered if freq_to_band(from_tens_hz(c.rxfreq)) == band
            ]
        if mode:
            filtered = [c for c in filtered if c.mode.upper() == mode.upper()]

        # Rate calculation — rolling windows
        def _count_since(contacts: list, seconds: float) -> int:
            cutoff = now.timestamp() - seconds
            return sum(1 for c in contacts if c.received_at.timestamp() > cutoff)

        rate_10m = _count_since(filtered, 600) * 6  # extrapolate to hourly
        rate_30m = _count_since(filtered, 1800) * 2
        rate_60m = _count_since(filtered, 3600)

        # Rate derivative (Patton P2) — compare last 5 min to previous 5 min
        recent_5m = _count_since(filtered, 300)
        cutoff_10m = now.timestamp() - 600
        cutoff_5m = now.timestamp() - 300
        prev_5m = sum(
            1
            for c in filtered
            if cutoff_10m < c.received_at.timestamp() <= cutoff_5m
        )
        rate_derivative = (recent_5m - prev_5m) * 12  # per hour rate change

        # Per-band breakdown
        band_breakdown: dict[str, dict[str, int]] = {}
        for c in log:
            b = freq_to_band(from_tens_hz(c.rxfreq))
            if b not in band_breakdown:
                band_breakdown[b] = {"qsos": 0, "mults": 0, "points": 0}
            band_breakdown[b]["qsos"] += 1
            band_breakdown[b]["mults"] += c.is_multiplier1
            band_breakdown[b]["points"] += c.points

        # Per-mode breakdown
        mode_breakdown: dict[str, dict[str, int]] = {}
        for c in log:
            m = c.mode
            if m not in mode_breakdown:
                mode_breakdown[m] = {"qsos": 0, "mults": 0, "points": 0}
            mode_breakdown[m]["qsos"] += 1
            mode_breakdown[m]["mults"] += c.is_multiplier1
            mode_breakdown[m]["points"] += c.points

        # Hourly summary
        hourly: dict[str, int] = {}
        for c in log:
            if c.timestamp:
                hour = c.timestamp[:13]  # "2026-11-28 14"
                hourly[hour] = hourly.get(hour, 0) + 1

        # Run vs S&P
        run_count = sum(1 for c in log if c.is_run_qso)
        sp_count = total - run_count
        run_points = sum(c.points for c in log if c.is_run_qso)
        sp_points = sum(c.points for c in log if not c.is_run_qso)

    result: dict[str, Any] = {
        "score": score_data,
        "rate": {
            "rate_10m": rate_10m,
            "rate_30m": rate_30m,
            "rate_60m": rate_60m,
            "rate_derivative": rate_derivative,
        },
        "band_breakdown": band_breakdown,
        "mode_breakdown": mode_breakdown,
        "hourly_summary": hourly,
        "run_vs_sp": {
            "run_qsos": run_count,
            "sp_qsos": sp_count,
            "run_points": run_points,
            "sp_points": sp_points,
            "run_pct": round(run_count / total * 100, 1) if total else 0,
        },
        "total_qsos": total,
    }

    # Flag discrepancy between Score XML and observed contacts
    score_total = score_data.get("total_qsos", 0)
    if score_total > total:
        result["score_discrepancy"] = {
            "score_xml_qsos": score_total,
            "observed_qsos": total,
            "missed": score_total - total,
            "reason": (
                "Rate, breakdown, and run/S&P stats reflect only QSOs "
                "observed live. Score totals come from N1MM's cumulative XML."
            ),
        }

    return result


# ---------------------------------------------------------------------------
# Tool 6: n1mm_multipliers — Mult Grid & Needs
# ---------------------------------------------------------------------------
@mcp.tool()
def n1mm_multipliers(
    band: str | None = None,
    station_name: str | None = None,
) -> dict[str, Any]:
    """Multiplier status — worked mults, mult map, and available needs.

    Returns total mults worked, per-band mult grid, unworked mults
    currently spotted, and mult value analysis.

    Args:
        band: Filter to specific band.
        station_name: Station to query.
    """
    state = _get_state()
    station = state.resolve_station(station_name)
    if station is None:
        names = state.get_station_names()
        if not names:
            return _disconnected_error()
        return _station_error(names)

    with station.contact_lock:
        log = station.contact_log

        # Total mults
        total_m1 = sum(1 for c in log if c.is_multiplier1)
        total_m2 = sum(1 for c in log if c.is_multiplier2)
        total_m3 = sum(1 for c in log if c.is_multiplier3)

        # Per-band mults
        band_mults: dict[str, dict[str, int]] = {}
        for c in log:
            b = freq_to_band(from_tens_hz(c.rxfreq))
            if b not in band_mults:
                band_mults[b] = {"m1": 0, "m2": 0, "m3": 0}
            band_mults[b]["m1"] += c.is_multiplier1
            band_mults[b]["m2"] += c.is_multiplier2
            band_mults[b]["m3"] += c.is_multiplier3

        # Mult map — zones/sections/countries worked per band
        mult_map: dict[str, list[str]] = {}
        for c in log:
            if c.is_multiplier1:
                b = freq_to_band(from_tens_hz(c.rxfreq))
                key = c.zone or c.section or c.country_prefix
                if key:
                    if b not in mult_map:
                        mult_map[b] = []
                    if key not in mult_map[b]:
                        mult_map[b].append(key)

        # Worked mult identifiers for "needs" calculation
        worked: set[tuple[str, str]] = set()
        for c in log:
            if c.is_multiplier1:
                b = freq_to_band(from_tens_hz(c.rxfreq))
                key = c.zone or c.section or c.country_prefix
                if key:
                    worked.add((b, key))

    # Unworked mults currently spotted
    needs: list[dict[str, Any]] = []
    with station.spot_lock:
        for spot in station.spot_map.values():
            if "mult" in spot.status_list.lower():
                spot_band = freq_to_band(from_spot_freq(spot.frequency))
                if band and spot_band != band:
                    continue
                needs.append(
                    {
                        "dxcall": spot.dxcall,
                        "frequency_mhz": from_spot_freq(spot.frequency),
                        "band": spot_band,
                        "status": spot.status,
                    }
                )

    # Mult value
    with station.contact_lock:
        mult_pts = [c.points for c in log if c.is_multiplier1]
        nonmult_pts = [c.points for c in log if not c.is_multiplier1]
        avg_mult = round(sum(mult_pts) / len(mult_pts), 1) if mult_pts else 0
        avg_nonmult = round(sum(nonmult_pts) / len(nonmult_pts), 1) if nonmult_pts else 0

    result: dict[str, Any] = {
        "total_mults": {"mult1": total_m1, "mult2": total_m2, "mult3": total_m3},
        "band_mults": band_mults,
        "mult_map": mult_map,
        "needs": needs,
        "mult_value": {"avg_mult_points": avg_mult, "avg_nonmult_points": avg_nonmult},
    }
    if band:
        result["filter_band"] = band

    # Cross-reference Score XML for discrepancy
    with station.score_lock:
        if station.score_state:
            score_qsos = sum(station.score_state.band_mode_qsos.values())
            with station.contact_lock:
                observed = len(station.contact_log)
            if score_qsos > observed:
                result["score_discrepancy"] = {
                    "score_xml_qsos": score_qsos,
                    "observed_qsos": observed,
                    "missed": score_qsos - observed,
                    "reason": (
                        "Multiplier data is only available for QSOs observed "
                        "live. Score XML reports %d QSOs but only %d were "
                        "seen by the MCP server." % (score_qsos, observed)
                    ),
                }

    return result


# ---------------------------------------------------------------------------
# Tool 7: n1mm_clock — Contest Timing & Pacing
# ---------------------------------------------------------------------------
@mcp.tool()
def n1mm_clock(
    duration_hours: float | None = None,
    target_score: int | None = None,
    target_qsos: int | None = None,
    min_gap_minutes: int = 30,
    station_name: str | None = None,
) -> dict[str, Any]:
    """Contest clock — timing, off-time, and pacing in one view.

    Args:
        duration_hours: Contest length (e.g., 48 for CQ WW, 24 for ARRL DX).
        target_score: Target score for pacing.
        target_qsos: Target QSO count for pacing.
        min_gap_minutes: Minimum gap to count as off-time (default 30).
        station_name: Station to query.
    """
    state = _get_state()
    station = state.resolve_station(station_name)
    if station is None:
        names = state.get_station_names()
        if not names:
            return _disconnected_error()
        return _station_error(names)

    now = datetime.now(timezone.utc)

    with station.contact_lock:
        log = station.contact_log
        total = len(log)

        if not log:
            # Check Score XML before claiming "no contacts"
            with station.score_lock:
                if station.score_state:
                    score_qsos = sum(station.score_state.band_mode_qsos.values())
                    if score_qsos > 0:
                        return {
                            "status": "no_observed_contacts",
                            "message": (
                                "No contacts observed live, but Score XML "
                                "reports %d QSOs logged before the MCP server "
                                "started. Timing and pacing data require live "
                                "contact observation." % score_qsos
                            ),
                            "score_xml_qsos": score_qsos,
                        }
            return {"status": "no_contacts", "message": "No contacts logged yet."}

        first_ts = log[0].timestamp
        last_ts = log[-1].timestamp

        # Elapsed time from first to last QSO
        elapsed_h = 0.0
        if first_ts and last_ts:
            try:
                t0 = datetime.fromisoformat(first_ts.replace(" ", "T"))
                t1 = datetime.fromisoformat(last_ts.replace(" ", "T"))
                elapsed_h = (t1 - t0).total_seconds() / 3600
            except ValueError:
                pass

        # Off-time detection
        off_periods: list[dict[str, Any]] = []
        gap_threshold = min_gap_minutes * 60
        for i in range(1, len(log)):
            try:
                prev_t = datetime.fromisoformat(log[i - 1].timestamp.replace(" ", "T"))
                curr_t = datetime.fromisoformat(log[i].timestamp.replace(" ", "T"))
                gap = (curr_t - prev_t).total_seconds()
                if gap >= gap_threshold:
                    off_periods.append(
                        {
                            "start": log[i - 1].timestamp,
                            "end": log[i].timestamp,
                            "duration_minutes": round(gap / 60, 1),
                        }
                    )
            except ValueError:
                continue

        total_off_min = sum(p["duration_minutes"] for p in off_periods)

    # Score for pacing
    current_score = 0
    with station.score_lock:
        if station.score_state:
            current_score = station.score_state.score

    result: dict[str, Any] = {
        "clock": {
            "first_qso": first_ts,
            "last_qso": last_ts,
            "elapsed_hours": round(elapsed_h, 2),
            "current_utc": now.isoformat(),
            "total_qsos": total,
        },
        "off_time": {
            "periods": off_periods,
            "total_off_minutes": round(total_off_min, 1),
        },
    }

    if duration_hours:
        remaining = max(0, duration_hours - elapsed_h)
        result["clock"]["remaining_hours"] = round(remaining, 2)

    # Pacing
    pace: dict[str, Any] = {}
    if elapsed_h > 0:
        qsos_per_hour = total / elapsed_h
        pace["current_qso_rate"] = round(qsos_per_hour, 1)

        if target_qsos and elapsed_h > 0:
            remaining_h = (duration_hours or 48) - elapsed_h
            needed = target_qsos - total
            if remaining_h > 0 and needed > 0:
                pace["qsos_needed"] = needed
                pace["required_rate"] = round(needed / remaining_h, 1)
            pace["projected_qsos"] = round(
                total + qsos_per_hour * max(0, (duration_hours or 48) - elapsed_h)
            )

        if target_score and current_score > 0 and elapsed_h > 0:
            score_rate = current_score / elapsed_h
            remaining_h = (duration_hours or 48) - elapsed_h
            pace["projected_score"] = round(current_score + score_rate * max(0, remaining_h))

    result["pace"] = pace

    return result


# ---------------------------------------------------------------------------
# Tool 8: n1mm_diagnostics — Health & Debug (Patton P1)
# ---------------------------------------------------------------------------
@mcp.tool()
def n1mm_diagnostics(station_name: str | None = None) -> dict[str, Any]:
    """Server health and diagnostics — connection, parse errors, memory.

    Essential for production debugging. First tool to call when something
    goes wrong during a contest.
    """
    state = _get_state()
    now = datetime.now(timezone.utc)

    status = state.connection_status()
    last_pkt = state.last_packet_at.isoformat() if state.last_packet_at else None
    age = (
        (now - state.last_packet_at).total_seconds() if state.last_packet_at else None
    )
    uptime = (now - state.started_at).total_seconds()

    # Per-station info
    stations = state.get_station_names()
    station_details: dict[str, Any] = {}
    for name in stations:
        s = state.resolve_station(name)
        if s:
            with s.contact_lock:
                contact_count = len(s.contact_log)
            with s.spot_lock:
                spot_map_size = len(s.spot_map)
            with s.radio_lock:
                contest = s.station_info.contest_name
            station_details[name] = {
                "contact_log_size": contact_count,
                "spot_map_size": spot_map_size,
                "contest": contest,
            }

    return {
        "status": status,
        "last_packet_received": last_pkt,
        "last_packet_age_seconds": round(age, 1) if age else None,
        "packets_received_total": state.packets_received,
        "parse_errors": state.parse_errors.to_dict(),
        "stations_seen": stations,
        "station_details": station_details,
        "uptime_seconds": round(uptime, 1),
        "version": __version__,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    """CLI entry point for n1mm-mcp."""
    import argparse
    import logging

    parser = argparse.ArgumentParser(
        prog="n1mm-mcp",
        description="MCP server for N1MM Logger+ contest state via UDP broadcast",
    )
    parser.add_argument("-p", "--port", type=int, default=12060, help="UDP listen port")
    parser.add_argument("-b", "--bind", default="0.0.0.0", help="Bind address")
    parser.add_argument(
        "--heartbeat-timeout",
        type=int,
        default=DEFAULT_HEARTBEAT_TIMEOUT,
        help="Seconds before stale state",
    )
    parser.add_argument(
        "--stale-timeout",
        type=int,
        default=DEFAULT_STALE_TIMEOUT,
        help="Seconds before disconnected",
    )
    parser.add_argument(
        "--max-spots", type=int, default=DEFAULT_MAX_SPOTS, help="Max spot buffer size"
    )
    parser.add_argument(
        "--spot-ttl", type=int, default=DEFAULT_SPOT_TTL // 60, help="Spot TTL in minutes"
    )
    parser.add_argument(
        "--transport", default="stdio", choices=["stdio", "streamable-http"]
    )
    parser.add_argument("--list-tools", action="store_true", help="List tools and exit")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    if args.list_tools:
        tools = [
            "n1mm_current_state",
            "n1mm_lookup",
            "n1mm_contacts",
            "n1mm_bandmap",
            "n1mm_performance",
            "n1mm_multipliers",
            "n1mm_clock",
            "n1mm_diagnostics",
        ]
        for t in tools:
            print(t)
        return

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    global _state
    _state = StateEngine(
        heartbeat_timeout=args.heartbeat_timeout,
        stale_timeout=args.stale_timeout,
        max_spots=args.max_spots,
        spot_ttl=args.spot_ttl * 60,  # CLI is minutes, internal is seconds
    )

    # Start listener
    is_mock = os.environ.get("N1MM_MCP_MOCK", "").strip() in ("1", "true", "yes")
    if is_mock:
        from .listener import MockListener

        listener = MockListener(_state)
    else:
        from .listener import UDPListener

        listener = UDPListener(_state, port=args.port, bind_addr=args.bind)

    listener.start()

    if args.transport == "streamable-http":
        mcp.run(transport="streamable-http", port=8008)
    else:
        mcp.run(transport="stdio")
