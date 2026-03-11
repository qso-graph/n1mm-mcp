"""Functional tests for StateEngine — callsign mapping and contest backfill."""

from n1mm_mcp.models import RadioState, ScoreState, StationInfo
from n1mm_mcp.state import StateEngine


def _engine() -> StateEngine:
    return StateEngine()


class TestCallsignStationMapping:
    """Fix: dynamicresults uses call= not StationName — must route correctly."""

    def test_radioinfo_registers_mapping(self):
        engine = _engine()
        radio = RadioState(radio_nr=1, mycall="KI7MT", station_name="I9-LAPTOP")
        engine.handle_radioinfo("I9-LAPTOP", radio)

        assert engine._call_to_station["KI7MT"] == "I9-LAPTOP"

    def test_score_routes_via_callsign(self):
        """Score with call=KI7MT should land on I9-LAPTOP, not create phantom."""
        engine = _engine()
        # RadioInfo arrives first with StationName
        radio = RadioState(radio_nr=1, mycall="KI7MT")
        engine.handle_radioinfo("I9-LAPTOP", radio)

        # DynamicResults arrives with call=KI7MT (no StationName)
        score = ScoreState(contest="POTA", call="KI7MT", score=42)
        engine.handle_score("KI7MT", score)

        # Should be ONE station (I9-LAPTOP), not two
        assert engine.get_station_names() == ["I9-LAPTOP"]
        station = engine.resolve_station("I9-LAPTOP")
        assert station is not None
        assert station.score_state is not None
        assert station.score_state.score == 42

    def test_resolve_station_by_callsign(self):
        """resolve_station('KI7MT') should return I9-LAPTOP station."""
        engine = _engine()
        radio = RadioState(radio_nr=1, mycall="KI7MT")
        engine.handle_radioinfo("I9-LAPTOP", radio)

        station = engine.resolve_station("KI7MT")
        assert station is not None
        assert station.station_name == "I9-LAPTOP"

    def test_cold_start_fallback(self):
        """No RadioInfo yet — Score with call creates station using call as name."""
        engine = _engine()
        score = ScoreState(contest="POTA", call="KI7MT", score=10)
        engine.handle_score("KI7MT", score)

        # Falls back to call as station name (safe for cold start)
        assert "KI7MT" in engine.get_station_names()
        station = engine.resolve_station("KI7MT")
        assert station is not None
        assert station.score_state.score == 10

    def test_no_phantom_station(self):
        """Multiple Score packets should not create phantom stations."""
        engine = _engine()
        radio = RadioState(radio_nr=1, mycall="KI7MT")
        engine.handle_radioinfo("I9-LAPTOP", radio)

        for i in range(5):
            score = ScoreState(contest="POTA", call="KI7MT", score=i * 10)
            engine.handle_score("KI7MT", score)

        assert engine.get_station_names() == ["I9-LAPTOP"]
        assert engine.resolve_station("I9-LAPTOP").score_state.score == 40


class TestContestNameBackfill:
    """Fix: contest_name empty when AppInfo never arrives — backfill from Score."""

    def test_backfill_from_score(self):
        """Score.contest populates empty contest_name."""
        engine = _engine()
        radio = RadioState(radio_nr=1, mycall="KI7MT")
        engine.handle_radioinfo("I9-LAPTOP", radio)

        score = ScoreState(contest="POTA", call="KI7MT", score=5)
        engine.handle_score("KI7MT", score)

        station = engine.resolve_station("I9-LAPTOP")
        assert station.station_info.contest_name == "POTA"

    def test_appinfo_not_overwritten(self):
        """AppInfo is authoritative — Score should not overwrite it."""
        engine = _engine()
        info = StationInfo(
            contest_name="CQ-WW-CW", station_name="I9-LAPTOP", mycall="KI7MT"
        )
        engine.handle_appinfo("I9-LAPTOP", info)

        radio = RadioState(radio_nr=1, mycall="KI7MT")
        engine.handle_radioinfo("I9-LAPTOP", radio)

        score = ScoreState(contest="POTA", call="KI7MT", score=5)
        engine.handle_score("KI7MT", score)

        station = engine.resolve_station("I9-LAPTOP")
        assert station.station_info.contest_name == "CQ-WW-CW"

    def test_no_backfill_when_score_empty(self):
        """Empty Score.contest should not blank out contest_name."""
        engine = _engine()
        info = StationInfo(
            contest_name="CQ-WW-CW", station_name="I9-LAPTOP", mycall="KI7MT"
        )
        engine.handle_appinfo("I9-LAPTOP", info)

        radio = RadioState(radio_nr=1, mycall="KI7MT")
        engine.handle_radioinfo("I9-LAPTOP", radio)

        score = ScoreState(contest="", call="KI7MT", score=5)
        engine.handle_score("KI7MT", score)

        station = engine.resolve_station("I9-LAPTOP")
        assert station.station_info.contest_name == "CQ-WW-CW"
