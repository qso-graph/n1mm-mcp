"""Functional tests for StateEngine — callsign mapping, contest backfill, discrepancy."""

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
        assert engine.score_view(station) is not None
        assert engine.score_view(station)["score"].score == 42

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
        assert engine.score_view(station)["score"].score == 10

    def test_no_phantom_station(self):
        """Multiple Score packets should not create phantom stations."""
        engine = _engine()
        radio = RadioState(radio_nr=1, mycall="KI7MT")
        engine.handle_radioinfo("I9-LAPTOP", radio)

        for i in range(5):
            score = ScoreState(contest="POTA", call="KI7MT", score=i * 10)
            engine.handle_score("KI7MT", score)

        assert engine.get_station_names() == ["I9-LAPTOP"]
        assert engine.score_view(engine.resolve_station("I9-LAPTOP"))["score"].score == 40


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
        assert engine.score_view(station) is not None
        assert engine.score_view(station)["score"].total_qsos() == 14
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
        assert engine.score_view(station)["score"].total_qsos() == 1
        assert len(station.contact_log) == 1

    def test_tool_contacts_surfaces_discrepancy(self):
        """Integration: n1mm_contacts tool output includes score_discrepancy."""
        import n1mm_mcp.server as srv
        from n1mm_mcp.server import n1mm_contacts

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


class TestScoreTotal:
    """#11: N1MM's band="total" row is the total, not one more row to add."""

    # The breakdown from N1MM's External UDP Broadcasts documentation.
    DOC_BREAKDOWN = {
        ("80", "CW"): 2, ("20", "CW"): 1, ("40", "CW"): 1, ("total", "ALL"): 4,
    }

    def test_the_total_row_is_used(self):
        assert ScoreState(band_mode_qsos=self.DOC_BREAKDOWN).total_qsos() == 4

    def test_without_a_total_row_the_rows_are_summed(self):
        rows = {k: v for k, v in self.DOC_BREAKDOWN.items() if k[0] != "total"}
        assert ScoreState(band_mode_qsos=rows).total_qsos() == 4

    def test_mode_all_on_a_band_is_not_the_total(self):
        rows = {("20", "CW"): 1, ("20", "PH"): 2, ("20", "ALL"): 3, ("total", "ALL"): 6}
        assert ScoreState(band_mode_qsos=rows).total_qsos() == 6

    def test_no_false_discrepancy_from_the_documented_packet(self):
        """4 QSOs seen, total row says 4: no "8 QSOs but only 4 seen" (the 0.1.7 bug)."""
        import n1mm_mcp.server as srv

        engine = _engine()
        engine.handle_radioinfo("RUN", RadioState(radio_nr=1, mycall="W1AW"))
        for i, f in enumerate((350000, 350100, 1400000, 700000)):
            engine.handle_contactinfo("RUN", Contact(call=f"K{i}AA", rxfreq=f, mode="CW", guid=str(i)))
        engine.handle_score("W1AW", ScoreState(contest="CQWWCW", call="W1AW", score=12,
                                               band_mode_qsos=dict(self.DOC_BREAKDOWN)))
        srv._state = engine
        for tool in (srv.n1mm_performance, srv.n1mm_multipliers, srv.n1mm_contacts):
            result = tool()
            assert "score_discrepancy" not in result, tool.__name__
        assert srv.n1mm_performance()["score"]["total_qsos"] == 4


class TestMultiOpScore:
    """#12: the score belongs to the contest call, which every multi-op station shares."""

    def _two_stations(self) -> StateEngine:
        engine = _engine()
        for name in ("RUN", "MULT"):
            engine.handle_appinfo(name, StationInfo(contest_name="CQWWCW", station_name=name, mycall="K3LR"))
            engine.handle_radioinfo(name, RadioState(radio_nr=1, mycall="K3LR"))
        engine.handle_contactinfo("RUN", Contact(call="W1AW", mycall="K3LR", rxfreq=1400000, mode="CW", guid="a"))
        engine.handle_contactinfo("MULT", Contact(call="W2AW", mycall="K3LR", rxfreq=700000, mode="CW", guid="b"))
        engine.handle_score("K3LR", ScoreState(contest="CQWWCW", call="K3LR", score=99,
                                               band_mode_qsos={("20", "CW"): 1, ("40", "CW"): 1,
                                                               ("total", "ALL"): 2}))
        return engine

    def test_each_station_shows_the_shared_score(self):
        engine = self._two_stations()
        assert sorted(engine.get_station_names()) == ["MULT", "RUN"]  # no "K3LR" partition
        for name in ("RUN", "MULT"):
            view = engine.score_view(engine.resolve_station(name))
            assert view["score"].score == 99
            assert view["stations"] == ["MULT", "RUN"]
            assert view["observed_qsos"] == 2  # both stations' contacts

    def test_tools_label_the_score_as_shared(self):
        import n1mm_mcp.server as srv

        srv._state = self._two_stations()
        for name in ("RUN", "MULT"):
            score = srv.n1mm_performance(station_name=name)["score"]
            assert score["total_score"] == 99 and score["total_qsos"] == 2
            assert score["shared"]["call"] == "K3LR"
            assert score["shared"]["stations"] == ["MULT", "RUN"]
            assert "all 2 stations" in score["shared"]["note"]
            # 2 QSOs in the score, 2 seen across the call: no discrepancy
            assert "score_discrepancy" not in srv.n1mm_performance(station_name=name)

    def test_a_single_op_score_is_not_labelled_shared(self):
        import n1mm_mcp.server as srv

        engine = _engine()
        engine.handle_radioinfo("I9-LAPTOP", RadioState(radio_nr=1, mycall="KI7MT"))
        engine.handle_score("KI7MT", ScoreState(contest="POTA", call="KI7MT", score=5))
        srv._state = engine
        assert "shared" not in srv.n1mm_performance()["score"]

    def test_a_score_for_another_contest_is_not_shown(self):
        engine = self._two_stations()
        engine.handle_appinfo("RUN", StationInfo(contest_name="ARRLDXCW", station_name="RUN", mycall="K3LR"))
        assert engine.score_view(engine.resolve_station("RUN")) is None
        assert engine.score_view(engine.resolve_station("MULT"))["score"].score == 99

    def test_a_station_known_only_from_contacts_gets_the_score(self):
        engine = _engine()
        engine.handle_contactinfo("FD-2", Contact(call="W1AW", mycall="w1fd", rxfreq=700000, mode="PH", guid="x"))
        engine.handle_score("W1FD", ScoreState(contest="ARRL-FD", call="W1FD", score=8))
        assert engine.get_station_names() == ["FD-2"]
        assert engine.score_view(engine.resolve_station("FD-2"))["score"].score == 8
