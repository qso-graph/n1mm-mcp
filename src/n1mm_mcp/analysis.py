"""Phase 2 analysis (#9): SO2R, networked stations, DXpedition pileups.

Pure functions over StationState.snapshot() copies, so no lock is held while they run.
Everything comes from N1MM's UDP packets: no rig is read. Times are when the packets
arrived (received_at), as the Phase 1 rate tools use.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from .frequency import freq_to_band, from_tens_hz
from .models import Contact, RadioState
from .state import DEFAULT_MAX_RADIO_EVENTS

# A gap between two RadioInfo packets longer than this is not counted: N1MM sends
# RadioInfo every 10 seconds and immediately on any change (N1MM's External UDP
# Broadcasts page), so a longer gap means N1MM or the network stopped.
GAP_CAP_SECONDS = 120.0
# Gaps between QSOs at least this long count as dead air in a pileup.
DEAD_AIR_MINUTES = 2.0


def _band(radio: RadioState) -> str:
    return freq_to_band(from_tens_hz(radio.freq_hz))


def contact_band(c: Contact) -> str:
    return freq_to_band(from_tens_hz(c.rxfreq))


def _pct(part: float, whole: float) -> float:
    return round(part * 100 / whole, 1) if whole else 0.0


def _rate(contacts: list[Contact], now: datetime, minutes: float) -> int:
    """QSOs in the last `minutes`, per hour."""
    cutoff = now - timedelta(minutes=minutes)
    n = sum(1 for c in contacts if c.received_at > cutoff)
    return round(n * 60 / minutes)


def radio_dict(r: RadioState) -> dict[str, Any]:
    return {
        "band": _band(r),
        "freq_mhz": from_tens_hz(r.freq_hz),
        "tx_freq_mhz": from_tens_hz(r.tx_freq_hz),
        "mode": r.mode,
        "is_running": r.is_running,
        "is_transmitting": r.is_transmitting,
        "is_split": r.is_split,
        "is_connected": r.is_connected,
        "op_call": r.op_call,
    }


# ---------------------------------------------------------------------------
# SO2R
# ---------------------------------------------------------------------------

def so2r(snap: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Two-radio state and timing for one station."""
    radios: dict[int, RadioState] = snap["radios"]
    events: list[RadioState] = sorted(snap["radio_events"], key=lambda e: e.received_at)
    contacts: list[Contact] = snap["contacts"]
    seen = sorted({e.radio_nr for e in events} | set(radios))

    result: dict[str, Any] = {"station_name": snap["station_name"], "radios_seen": seen}
    if len(seen) < 2:
        result["so2r"] = False
        result["message"] = (
            "Only one radio has reported. SO2R figures need N1MM set up for two radios "
            "(RadioInfo from radio 1 and radio 2)."
        )
        return result
    result["so2r"] = True

    current: dict[str, Any] = {f"radio_{nr}": radio_dict(radios[nr]) for nr in sorted(radios)}
    latest = max(radios.values(), key=lambda r: r.received_at)
    bands = {_band(r) for r in radios.values()}
    # N1MM's ActiveRadioNr is the transmit focus, FocusRadioNr the receive focus.
    current["transmit_focus_radio"] = latest.active_radio_nr
    current["receive_focus_radio"] = latest.focus_radio_nr
    current["is_stereo"] = latest.is_stereo
    current["same_band"] = len(radios) >= 2 and len(bands) == 1 and "unknown" not in bands
    result["now"] = current

    # Timing, from the RadioInfo history
    last: dict[int, RadioState] = {}
    tx: defaultdict[int, float] = defaultdict(float)
    band_time: dict[int, defaultdict[str, float]] = {nr: defaultdict(float) for nr in seen}
    observed = same_band = 0.0
    swaps = focus_switches = 0
    prev_active = prev_focus = None
    for i, e in enumerate(events):
        if prev_active is not None and e.active_radio_nr != prev_active:
            swaps += 1
        if prev_focus is not None and e.focus_radio_nr != prev_focus:
            focus_switches += 1
        prev_active, prev_focus = e.active_radio_nr, e.focus_radio_nr
        last[e.radio_nr] = e
        end = events[i + 1].received_at if i + 1 < len(events) else now
        dt = min((end - e.received_at).total_seconds(), GAP_CAP_SECONDS)
        if dt <= 0:
            continue
        observed += dt
        for nr, r in last.items():
            if r.is_transmitting:
                tx[nr] += dt
            band_time[nr][_band(r)] += dt
        if len(last) >= 2 and len({_band(r) for r in last.values()}) == 1:
            same_band += dt

    # What span the figures below actually cover (#21).
    #
    # radio_events is a bounded history: N1MM sends a RadioInfo packet per radio
    # every ten seconds plus one on every change, so two radios fill 50,000 in
    # roughly 40 to 70 hours and the oldest then drop off. Everything in this
    # block is computed from what is left, and without saying so a transmit
    # share read at hour 40 looks like the whole contest.
    #
    # `truncated` is reported when the history is full rather than when a drop
    # is observed, because a full deque and a deque that has just dropped a
    # packet are the same thing from here. Erring towards saying the figures are
    # partial is the safe direction for a number somebody reads as a contest
    # total.
    result["timing"] = {
        "from_utc": events[0].received_at.isoformat() if events else None,
        "truncated": len(events) >= DEFAULT_MAX_RADIO_EVENTS,
        "observed_minutes": round(observed / 60, 1),
        "transmit_pct": {f"radio_{nr}": _pct(tx[nr], observed) for nr in seen},
        "transmit_note": (
            "Transmit time N1MM keyed (macros, its CW keyer). N1MM's IsTransmitting stays "
            "false for a paddle or microphone PTT, so that time isn't counted."
        ),
        "minutes_by_band": {
            f"radio_{nr}": {
                b: round(t / 60, 1)
                for b, t in sorted(band_time[nr].items(), key=lambda bt: -bt[1])
            }
            for nr in seen
        },
        "truncated_note": (
            "The RadioInfo history is full, so these figures start at from_utc and not at the "
            "start of the contest."
            if len(events) >= DEFAULT_MAX_RADIO_EVENTS
            else "The RadioInfo history covers everything received since from_utc."
        ),
        "same_band_pct": _pct(same_band, observed),
        "transmit_focus_swaps": swaps,
        "receive_focus_swaps": focus_switches,
    }

    # QSOs per radio, and QSOs on one radio while the other was running
    per_radio = Counter(c.radio_nr for c in contacts)
    by_radio = {nr: [e for e in events if e.radio_nr == nr] for nr in seen}
    times = {nr: [e.received_at for e in evs] for nr, evs in by_radio.items()}
    overlap: Counter[int] = Counter()
    for c in contacts:
        for other in seen:
            if other == c.radio_nr:
                continue
            k = bisect_right(times[other], c.received_at)
            if k and by_radio[other][k - 1].is_running:
                overlap[c.radio_nr] += 1
                break
    total = len(contacts)
    result["qsos"] = {
        "total": total,
        "by_radio": {f"radio_{nr}": per_radio.get(nr, 0) for nr in seen},
        "pct_by_radio": {f"radio_{nr}": _pct(per_radio.get(nr, 0), total) for nr in seen},
        "run_by_radio": {
            f"radio_{nr}": sum(1 for c in contacts if c.radio_nr == nr and c.is_run_qso) for nr in seen
        },
        "while_other_radio_running": {f"radio_{nr}": overlap.get(nr, 0) for nr in seen},
    }
    return result


# ---------------------------------------------------------------------------
# Networked stations (multi-op)
# ---------------------------------------------------------------------------

def _minutes_on_band(contacts: list[Contact], now: datetime) -> tuple[str, float | None, int]:
    """Current band from the QSOs, minutes since the first QSO of the current band run,
    and band changes in the last hour."""
    if not contacts:
        return "", None, 0
    ordered = sorted(contacts, key=lambda c: c.received_at)
    band = contact_band(ordered[-1])
    start = ordered[-1].received_at
    for c in reversed(ordered):
        if contact_band(c) != band:
            break
        start = c.received_at
    hour_ago = now - timedelta(hours=1)
    changes = sum(
        1 for a, b in zip(ordered, ordered[1:])
        if b.received_at > hour_ago and contact_band(a) != contact_band(b)
    )
    return band, round((now - start).total_seconds() / 60, 1), changes


def station_row(snap: dict[str, Any], now: datetime) -> dict[str, Any]:
    contacts: list[Contact] = snap["contacts"]
    radios: dict[int, RadioState] = snap["radios"]
    last_qso = max((c.received_at for c in contacts), default=None)
    last_radio = max((r.received_at for r in radios.values()), default=None)
    heard = max([t for t in (last_qso, last_radio) if t], default=None)
    op = ""
    if radios:
        op = max(radios.values(), key=lambda r: r.received_at).op_call
    if not op and contacts:
        op = contacts[-1].operator
    band, on_band, changes = _minutes_on_band(contacts, now)
    hour_ago = now - timedelta(hours=1)
    return {
        "station_name": snap["station_name"],
        "mycall": snap["info"].mycall,
        "contest": snap["info"].contest_name,
        "operator": op,
        "radios": {f"radio_{nr}": radio_dict(radios[nr]) for nr in sorted(radios)},
        "qsos": len(contacts),
        "rate_10m": _rate(contacts, now, 10),
        "rate_60m": _rate(contacts, now, 60),
        "mults_last_60m": sum(c.is_multiplier1 for c in contacts if c.received_at > hour_ago),
        "minutes_since_last_qso": (
            round((now - last_qso).total_seconds() / 60, 1) if last_qso else None
        ),
        "qso_band": band,
        "minutes_on_qso_band": on_band,
        "band_changes_last_60m": changes,
        "last_heard_seconds": round((now - heard).total_seconds()) if heard else None,
    }


def network(snaps: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
    rows = [station_row(s, now) for s in snaps]

    # Who is on which band and mode, by radio
    on: dict[str, list[dict[str, Any]]] = {}
    for s in snaps:
        for nr, r in sorted(s["radios"].items()):
            b = _band(r)
            if b == "unknown":
                continue
            on.setdefault(b, []).append({"station_name": s["station_name"], "radio": nr, "mode": r.mode})
    same_band_mode = [
        {"band": b, "mode": m, "stations": sorted({x["station_name"] for x in xs if x["mode"] == m})}
        for b, xs in sorted(on.items())
        for m in sorted({x["mode"] for x in xs})
        if len({x["station_name"] for x in xs if x["mode"] == m}) > 1
    ]

    # Operators, across all stations: this hour against the hour before
    hour, two = now - timedelta(hours=1), now - timedelta(hours=2)
    ops: dict[str, Counter[str]] = {}
    for s in snaps:
        for c in s["contacts"]:
            name = (c.operator or "").upper() or "(none)"
            cnt = ops.setdefault(name, Counter())
            cnt["qsos"] += 1
            if c.received_at > hour:
                cnt["last_60m"] += 1
            elif c.received_at > two:
                cnt["previous_60m"] += 1
    operators = [
        {"operator": name, "qsos": cnt["qsos"], "last_60m": cnt["last_60m"],
         "previous_60m": cnt["previous_60m"]}
        for name, cnt in sorted(ops.items(), key=lambda kv: -kv[1]["qsos"])
    ]
    return {
        "stations": rows,
        "total_qsos": sum(r["qsos"] for r in rows),
        "bands": on,
        "same_band_and_mode": same_band_mode,
        "operators": operators,
    }


# ---------------------------------------------------------------------------
# DXpedition pileup
# ---------------------------------------------------------------------------

def pileup(snap: dict[str, Any], now: datetime, window_minutes: int) -> dict[str, Any]:
    contacts: list[Contact] = sorted(snap["contacts"], key=lambda c: c.received_at)
    radios: dict[int, RadioState] = snap["radios"]
    start = now - timedelta(minutes=window_minutes)
    window = [c for c in contacts if c.received_at > start]

    # Dupes: a call already worked on the same band and mode, earlier in the log
    seen: set[tuple[str, str, str]] = set()
    dupes = 0
    for c in contacts:
        key = (c.call.upper(), contact_band(c), c.mode.upper())
        if key in seen and c.received_at > start:
            dupes += 1
        seen.add(key)

    n = len(window)
    continents = Counter((c.continent or "?").upper() for c in window)
    countries = Counter((c.country_prefix or "?").upper() for c in window)
    band_mode = Counter(f"{contact_band(c)} {c.mode}" for c in window)

    peak = 0
    times = [c.received_at for c in window]
    for i, t in enumerate(times):
        j = bisect_right(times, t + timedelta(minutes=10))
        peak = max(peak, (j - i) * 6)

    gaps: list[dict[str, Any]] = []
    for a, b in zip(window, window[1:]):
        m = (b.received_at - a.received_at).total_seconds() / 60
        if m >= DEAD_AIR_MINUTES:
            gaps.append({"from": a.received_at.isoformat(), "to": b.received_at.isoformat(),
                         "minutes": round(m, 1)})
    gaps.sort(key=lambda g: -g["minutes"])

    result: dict[str, Any] = {
        "station_name": snap["station_name"],
        "window_minutes": window_minutes,
        "qsos": n,
        "unique_calls": len({c.call.upper() for c in window}),
        "dupes": dupes,
        "run_pct": _pct(sum(1 for c in window if c.is_run_qso), n),
        "rate": {
            "last_5m": _rate(contacts, now, 5),
            "last_15m": _rate(contacts, now, 15),
            "last_60m": _rate(contacts, now, 60),
            "peak_10m_in_window": peak,
        },
        "by_continent": {k: {"qsos": v, "pct": _pct(v, n)} for k, v in continents.most_common()},
        "top_countries": [{"prefix": k, "qsos": v} for k, v in countries.most_common(10)],
        "by_band_mode": dict(band_mode.most_common()),
        "dead_air": {
            "minutes_since_last_qso": (
                round((now - contacts[-1].received_at).total_seconds() / 60, 1) if contacts else None
            ),
            "gaps_over_2m": len(gaps),
            "longest": gaps[:5],
        },
    }
    if radios:
        r = max(radios.values(), key=lambda x: x.received_at)
        active = radios.get(r.active_radio_nr, r)
        result["split"] = {
            "is_split": active.is_split,
            "rx_mhz": from_tens_hz(active.freq_hz),
            "tx_mhz": from_tens_hz(active.tx_freq_hz),
            "up_khz": (
                round((active.tx_freq_hz - active.freq_hz) / 100, 1) if active.is_split else 0.0
            ),
        }
    return result
