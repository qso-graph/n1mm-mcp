"""Functional tests for StateEngine — callsign mapping, contest backfill, discrepancy."""

import os

from n1mm_mcp.models import Contact, RadioState, ScoreState, StationInfo
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


class TestScoreDiscrepancy:
    """v0.1.4: Surface discrepancy when Score XML reports more QSOs than observed."""

    def _setup_station(self) -> StateEngine:
        engine = _engine()
        radio = RadioState(radio_nr=1, mycall="KI7MT")
        engine.handle_radioinfo("I9-LAPTOP", radio)
        return engine

    def test_discrepancy_when_score_exceeds_contacts(self):
        """Score says 14 QSOs but contact_log has 0 → discrepancy surfaced."""
        engine = self._setup_station()
        score = ScoreState(
            contest="POTA", call="KI7MT", score=7,
            band_mode_qsos={("20", "PH"): 5, ("12", "FT8"): 4, ("40", "PH"): 5},
        )
        engine.handle_score("KI7MT", score)

        station = engine.resolve_station("I9-LAPTOP")
        assert station.score_state is not None
        assert sum(station.score_state.band_mode_qsos.values()) == 14
        assert len(station.contact_log) == 0

    def test_no_discrepancy_when_counts_match(self):
        """Score matches contact_log → no discrepancy."""
        engine = self._setup_station()
        contact = Contact(call="W1AW", rxfreq=140850000, mode="CW", guid="abc")
        engine.handle_contactinfo("I9-LAPTOP", contact)
        score = ScoreState(
            contest="POTA", call="KI7MT", score=1,
            band_mode_qsos={("20", "CW"): 1},
        )
        engine.handle_score("KI7MT", score)

        station = engine.resolve_station("I9-LAPTOP")
        assert sum(station.score_state.band_mode_qsos.values()) == 1
        assert len(station.contact_log) == 1

    def test_tool_contacts_surfaces_discrepancy(self):
        """Integration: n1mm_contacts tool output includes score_discrepancy."""
        from n1mm_mcp.server import n1mm_contacts
        import n1mm_mcp.server as srv

        engine = self._setup_station()
        score = ScoreState(
            contest="POTA", call="KI7MT", score=7,
            band_mode_qsos={("20", "PH"): 5, ("12", "FT8"): 9},
        )
        engine.handle_score("KI7MT", score)
        srv._state = engine

        result = n1mm_contacts()
        assert "score_discrepancy" in result
        assert result["score_discrepancy"]["score_xml_qsos"] == 14
        assert result["score_discrepancy"]["missed"] == 14
        assert result["total_qsos"] == 0
