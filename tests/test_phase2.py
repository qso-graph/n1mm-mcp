"""Phase 2 (#9): n1mm_so2r, n1mm_network, n1mm_pileup, from synthetic N1MM packets."""

from datetime import datetime, timedelta, timezone

import pytest

import n1mm_mcp.server as srv
from n1mm_mcp import analysis
from n1mm_mcp.models import Contact, RadioState, ScoreState, StationInfo
from n1mm_mcp.state import StateEngine

T0 = datetime(2026, 11, 28, 14, 0, tzinfo=timezone.utc)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def radio(nr, mhz, minute, running=False, tx=False, active=1, focus=1, mode="CW", op="KI7MT",
          split=False, tx_mhz=None):
    return RadioState(
        radio_nr=nr, freq_hz=int(round(mhz * 100000)), mode=mode, mycall="K7XX", op_call=op,
        is_running=running, is_transmitting=tx, active_radio_nr=active, focus_radio_nr=focus,
        is_split=split, tx_freq_hz=int(round((tx_mhz or mhz) * 100000)), received_at=at(minute),
    )


def qso(call, mhz, minute, radio_nr=1, run=1, mode="CW", cont="EU", pfx="DL", op="KI7MT", mult=0, guid=None):
    return Contact(
        call=call, mycall="K7XX", rxfreq=int(round(mhz * 100000)), mode=mode, radio_nr=radio_nr,
        is_run_qso=run, continent=cont, country_prefix=pfx, operator=op, is_multiplier1=mult,
        guid=guid or f"{call}-{minute}", received_at=at(minute),
    )


@pytest.fixture(autouse=True)
def engine():
    e = StateEngine()
    old = srv._state
    srv._state = e
    yield e
    srv._state = old


# ── SO2R ─────────────────────────────────────────────────────────────────────

def so2r_station(e: StateEngine) -> None:
    """30 minutes of RadioInfo every 10 seconds, as N1MM sends it."""
    e.handle_appinfo("SO2R", StationInfo(contest_name="CQWWCW", station_name="SO2R", mycall="K7XX"))
    for k in range(180):
        m = k / 6
        swapped = 10 <= m < 20  # minutes 10-20: transmit and receive focus on radio 2
        focus = 2 if swapped else 1
        # Radio 1 runs on 20m throughout; it transmits except while radio 2 does.
        e.handle_radioinfo("SO2R", radio(1, 14.025, m, running=True, tx=not swapped, active=focus, focus=focus))
        e.handle_radioinfo("SO2R", radio(2, 7.010, m, tx=swapped, active=focus, focus=focus))
    e.handle_contactinfo("SO2R", qso("DL1AA", 14.025, 5, radio_nr=1))
    e.handle_contactinfo("SO2R", qso("F5BB", 7.010, 15, radio_nr=2, run=0))  # radio 1 running
    e.handle_contactinfo("SO2R", qso("G4CC", 14.025, 25, radio_nr=1))


def test_so2r_timing_swaps_and_qsos(engine):
    so2r_station(engine)
    r = analysis.so2r(engine.resolve_station("SO2R").snapshot(), at(30))
    assert r["so2r"] is True and r["radios_seen"] == [1, 2]
    assert r["now"]["transmit_focus_radio"] == 1 and r["now"]["same_band"] is False
    t = r["timing"]
    assert t["observed_minutes"] == 30.0
    # Radio 1 transmitted minutes 0-10 and 20-30; radio 2 minutes 10-20.
    assert t["transmit_pct"] == {"radio_1": 66.7, "radio_2": 33.3}
    assert t["minutes_by_band"]["radio_2"] == {"40m": 30.0}
    assert t["transmit_focus_swaps"] == 2 and t["receive_focus_swaps"] == 2
    assert "paddle" in t["transmit_note"]
    q = r["qsos"]
    assert q["by_radio"] == {"radio_1": 2, "radio_2": 1}
    assert q["while_other_radio_running"] == {"radio_1": 0, "radio_2": 1}
    assert q["run_by_radio"] == {"radio_1": 2, "radio_2": 0}


def test_so2r_gaps_longer_than_the_cap_are_not_air_time(engine):
    engine.handle_radioinfo("S", radio(1, 14.0, 0, tx=True))
    engine.handle_radioinfo("S", radio(2, 7.0, 0))
    r = analysis.so2r(engine.resolve_station("S").snapshot(), at(60))  # an hour of silence
    assert r["timing"]["observed_minutes"] == analysis.GAP_CAP_SECONDS / 60


def test_so2r_same_band_is_flagged(engine):
    engine.handle_radioinfo("S", radio(1, 14.010, 0))
    engine.handle_radioinfo("S", radio(2, 14.050, 0))
    r = analysis.so2r(engine.resolve_station("S").snapshot(), at(1))
    assert r["now"]["same_band"] is True and r["timing"]["same_band_pct"] == 100.0


def test_so2r_with_one_radio_says_so(engine):
    engine.handle_radioinfo("S", radio(1, 14.0, 0))
    r = srv.n1mm_so2r()
    assert r["so2r"] is False and "two radios" in r["message"]


def test_so2r_history_is_cleared_on_contest_change(engine):
    so2r_station(engine)
    engine.handle_appinfo("SO2R", StationInfo(contest_name="ARRLDXCW", station_name="SO2R", mycall="K7XX"))
    assert engine.resolve_station("SO2R").snapshot()["radio_events"] == []


# ── Network ──────────────────────────────────────────────────────────────────

def network_stations(e: StateEngine) -> None:
    for name, op, mhz in (("RUN", "N1AA", 14.025), ("MULT", "N2BB", 14.030), ("40M", "N3CC", 7.010)):
        e.handle_appinfo(name, StationInfo(contest_name="CQWWCW", station_name=name, mycall="K3LR"))
        e.handle_radioinfo(name, radio(1, mhz, 0, op=op))
    for i in range(6):  # RUN: 6 QSOs on 20m, one 40m QSO before them
        e.handle_contactinfo("RUN", qso(f"DL{i}AA", 14.025, 70 + i * 5, op="N1AA", mult=1 if i < 2 else 0))
    e.handle_contactinfo("RUN", qso("W1XX", 7.020, 65, op="N1AA"))
    e.handle_contactinfo("40M", qso("JA1AA", 7.010, 10, op="N3CC"))  # last QSO long ago
    e.handle_score("K3LR", ScoreState(contest="CQWWCW", call="K3LR", score=500,
                                      band_mode_qsos={("total", "ALL"): 8}))


def test_network_rows(engine):
    network_stations(engine)
    r = analysis.network([engine.resolve_station(n).snapshot() for n in ("RUN", "MULT", "40M")], at(100))
    rows = {x["station_name"]: x for x in r["stations"]}
    assert rows["RUN"]["operator"] == "N1AA" and rows["RUN"]["qsos"] == 7
    assert rows["RUN"]["qso_band"] == "20m" and rows["RUN"]["minutes_on_qso_band"] == 30.0
    assert rows["RUN"]["band_changes_last_60m"] == 1
    assert rows["RUN"]["mults_last_60m"] == 2
    assert rows["40M"]["minutes_since_last_qso"] == 90.0
    assert rows["MULT"]["qsos"] == 0 and rows["MULT"]["minutes_since_last_qso"] is None
    assert r["total_qsos"] == 8


def test_network_band_sharing_and_operators(engine):
    network_stations(engine)
    r = analysis.network([engine.resolve_station(n).snapshot() for n in ("RUN", "MULT", "40M")], at(100))
    assert {x["station_name"] for x in r["bands"]["20m"]} == {"RUN", "MULT"}
    assert r["same_band_and_mode"] == [{"band": "20m", "mode": "CW", "stations": ["MULT", "RUN"]}]
    ops = {o["operator"]: o for o in r["operators"]}
    assert ops["N1AA"]["qsos"] == 7 and ops["N1AA"]["last_60m"] == 7
    assert ops["N3CC"]["last_60m"] == 0


def test_network_tool_has_the_shared_score(engine):
    network_stations(engine)
    r = srv.n1mm_network()
    assert r["scores_by_call"]["K3LR"]["score"] == 500
    assert r["scores_by_call"]["K3LR"]["stations"] == ["40M", "MULT", "RUN"]
    assert len(r["stations"]) == 3


def test_network_with_no_stations(engine):
    assert srv.n1mm_network() == srv._disconnected_error()


# ── Pileup ───────────────────────────────────────────────────────────────────

def pileup_station(e: StateEngine) -> None:
    e.handle_radioinfo("DX", radio(1, 14.023, 0, running=True, split=True, tx_mhz=14.025, mode="CW"))
    calls = [("DL1AA", "EU", "DL"), ("JA1BB", "AS", "JA"), ("W1CC", "NA", "K"), ("DL1AA", "EU", "DL"),
             ("F5DD", "EU", "F"), ("K2EE", "NA", "K")]
    for i, (c, cont, pfx) in enumerate(calls):
        e.handle_contactinfo("DX", qso(c, 14.023, 50 + i, cont=cont, pfx=pfx))
    e.handle_contactinfo("DX", qso("VK3FF", 14.023, 59.5, cont="OC", pfx="VK"))
    e.handle_contactinfo("DX", qso("ZL2GG", 14.023, 20, cont="OC", pfx="ZL"))  # before a long gap


def test_pileup(engine):
    pileup_station(engine)
    r = analysis.pileup(engine.resolve_station("DX").snapshot(), at(60), 60)
    assert r["qsos"] == 8 and r["unique_calls"] == 7 and r["dupes"] == 1
    assert r["by_continent"]["EU"] == {"qsos": 3, "pct": 37.5}
    assert r["top_countries"][0] == {"prefix": "DL", "qsos": 2}
    assert r["rate"]["last_15m"] == 28  # 7 QSOs in 15 minutes
    assert r["rate"]["peak_10m_in_window"] == 42
    assert r["dead_air"]["longest"][0]["minutes"] == 30.0
    assert r["dead_air"]["minutes_since_last_qso"] == 0.5
    assert r["split"] == {"is_split": True, "rx_mhz": 14.023, "tx_mhz": 14.025, "up_khz": 2.0}


def test_pileup_window_is_validated(engine):
    pileup_station(engine)
    assert srv.n1mm_pileup(window_minutes=1)["error"] == "invalid_window"
    assert srv.n1mm_pileup(window_minutes=5000)["error"] == "invalid_window"
    assert "qsos" in srv.n1mm_pileup(window_minutes=15)


def test_deleted_qsos_are_left_out(engine):
    pileup_station(engine)
    engine.handle_contactdelete("DX", "VK3FF-59.5", "VK3FF", "20", "")
    r = analysis.pileup(engine.resolve_station("DX").snapshot(), at(60), 60)
    assert r["qsos"] == 7
