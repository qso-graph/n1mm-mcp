"""L2 unit tests for n1mm-mcp — frequency conversion + XML parsing.

Direct unit tests on frequency module and listener parsers.
No UDP or N1MM Logger+ required.

Test IDs: N1MM-L2-001 through N1MM-L2-040
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from n1mm_mcp.frequency import freq_to_band, from_spot_freq, from_tens_hz
from n1mm_mcp.listener import _bool, _int, _text
from n1mm_mcp.models import Contact, RadioState, ScoreState, StationInfo
from n1mm_mcp.state import StateEngine


# ---------------------------------------------------------------------------
# N1MM-L2-001..010: from_tens_hz
# ---------------------------------------------------------------------------


class TestFromTensHz:
    def test_20m(self):
        """N1MM-L2-001: 1407400 → 14.0740 MHz."""
        assert from_tens_hz(1407400) == pytest.approx(14.074, abs=0.0001)

    def test_40m(self):
        """N1MM-L2-002: 703000 → 7.0300 MHz."""
        assert from_tens_hz(703000) == pytest.approx(7.03, abs=0.0001)

    def test_zero(self):
        """N1MM-L2-003: 0 → 0.0."""
        assert from_tens_hz(0) == 0.0

    def test_160m(self):
        """N1MM-L2-004: 184000 → 1.8400 MHz."""
        assert from_tens_hz(184000) == pytest.approx(1.84, abs=0.0001)

    def test_6m(self):
        """N1MM-L2-005: 5031300 → 50.3130 MHz."""
        assert from_tens_hz(5031300) == pytest.approx(50.313, abs=0.0001)

    def test_truncation(self):
        """N1MM-L2-006: Result truncated to 4 decimal places."""
        result = from_tens_hz(712345)
        assert result == pytest.approx(7.1235, abs=0.00005)


# ---------------------------------------------------------------------------
# N1MM-L2-011..016: from_spot_freq
# ---------------------------------------------------------------------------


class TestFromSpotFreq:
    def test_khz_input(self):
        """N1MM-L2-011: 14195.0 kHz → 14.1950 MHz."""
        assert from_spot_freq("14195.0") == pytest.approx(14.195, abs=0.0001)

    def test_mhz_input(self):
        """N1MM-L2-012: 14.195 MHz → 14.1950 MHz."""
        assert from_spot_freq("14.195") == pytest.approx(14.195, abs=0.0001)

    def test_zero(self):
        """N1MM-L2-013: 0 → 0.0."""
        assert from_spot_freq("0") == 0.0

    def test_negative(self):
        """N1MM-L2-014: Negative value → 0.0."""
        assert from_spot_freq("-100") == 0.0

    def test_invalid_string(self):
        """N1MM-L2-015: Non-numeric → 0.0."""
        assert from_spot_freq("abc") == 0.0

    def test_empty_string(self):
        """N1MM-L2-016: Empty string → 0.0."""
        assert from_spot_freq("") == 0.0


# ---------------------------------------------------------------------------
# N1MM-L2-017..025: freq_to_band
# ---------------------------------------------------------------------------


class TestFreqToBand:
    def test_160m(self):
        """N1MM-L2-017: 1.84 MHz → 160m."""
        assert freq_to_band(1.84) == "160m"

    def test_80m(self):
        """N1MM-L2-018: 3.573 MHz → 80m."""
        assert freq_to_band(3.573) == "80m"

    def test_40m(self):
        """N1MM-L2-019: 7.074 MHz → 40m."""
        assert freq_to_band(7.074) == "40m"

    def test_20m(self):
        """N1MM-L2-020: 14.074 MHz → 20m."""
        assert freq_to_band(14.074) == "20m"

    def test_15m(self):
        """N1MM-L2-021: 21.074 MHz → 15m."""
        assert freq_to_band(21.074) == "15m"

    def test_10m(self):
        """N1MM-L2-022: 28.074 MHz → 10m."""
        assert freq_to_band(28.074) == "10m"

    def test_6m(self):
        """N1MM-L2-023: 50.313 MHz → 6m."""
        assert freq_to_band(50.313) == "6m"

    def test_zero(self):
        """N1MM-L2-024: 0.0 MHz → unknown."""
        assert freq_to_band(0.0) == "unknown"

    def test_out_of_band(self):
        """N1MM-L2-025: 100 MHz → unknown."""
        assert freq_to_band(100.0) == "unknown"

    def test_all_bands(self):
        """N1MM-L2-026: Representative frequency for each band."""
        cases = [
            (1.9, "160m"), (3.7, "80m"), (5.35, "60m"), (7.15, "40m"),
            (10.12, "30m"), (14.2, "20m"), (18.1, "17m"), (21.2, "15m"),
            (24.93, "12m"), (28.5, "10m"), (51.0, "6m"),
        ]
        for freq, expected in cases:
            assert freq_to_band(freq) == expected, f"{freq} should be {expected}"


# ---------------------------------------------------------------------------
# N1MM-L2-027..032: XML parsing helpers
# ---------------------------------------------------------------------------


class TestXmlHelpers:
    def test_text_present(self):
        """N1MM-L2-027: _text extracts tag text."""
        root = ET.fromstring("<root><Name>KI7MT</Name></root>")
        assert _text(root, "Name") == "KI7MT"

    def test_text_missing(self):
        """N1MM-L2-028: _text returns default for missing tag."""
        root = ET.fromstring("<root></root>")
        assert _text(root, "Name") == ""
        assert _text(root, "Name", "UNKNOWN") == "UNKNOWN"

    def test_int_valid(self):
        """N1MM-L2-029: _int parses integer string."""
        assert _int("42") == 42

    def test_int_invalid(self):
        """N1MM-L2-030: _int returns default for non-integer."""
        assert _int("abc") == 0
        assert _int("", 99) == 99

    def test_bool_true(self):
        """N1MM-L2-031: _bool parses true/1/yes."""
        assert _bool("true") is True
        assert _bool("True") is True
        assert _bool("1") is True

    def test_bool_false(self):
        """N1MM-L2-032: _bool parses false/0/other."""
        assert _bool("false") is False
        assert _bool("0") is False
        assert _bool("") is False


# ---------------------------------------------------------------------------
# N1MM-L2-033..037: StateEngine (additional coverage)
# ---------------------------------------------------------------------------


class TestStateEngineExtended:
    def test_empty_engine(self):
        """N1MM-L2-033: Fresh engine has no stations."""
        engine = StateEngine()
        assert engine.get_station_names() == []

    def test_resolve_none(self):
        """N1MM-L2-034: resolve_station returns None when empty."""
        engine = StateEngine()
        assert engine.resolve_station(None) is None

    def test_handle_contact(self):
        """N1MM-L2-035: Contact added to station log."""
        engine = StateEngine()
        radio = RadioState(radio_nr=1, mycall="KI7MT")
        engine.handle_radioinfo("LAPTOP", radio)

        contact = Contact(call="W1AW", rxfreq=140850000, mode="CW", guid="abc")
        engine.handle_contactinfo("LAPTOP", contact)

        station = engine.resolve_station("LAPTOP")
        assert len(station.contact_log) == 1
        assert station.contact_log[0].call == "W1AW"

    def test_contact_replace(self):
        """N1MM-L2-036: Contact replace updates existing contact."""
        engine = StateEngine()
        radio = RadioState(radio_nr=1, mycall="KI7MT")
        engine.handle_radioinfo("LAPTOP", radio)

        c1 = Contact(call="W1AW", rxfreq=140850000, mode="CW", guid="abc")
        engine.handle_contactinfo("LAPTOP", c1)

        c2 = Contact(call="W1AW", rxfreq=140850000, mode="SSB", guid="abc")
        engine.handle_contactreplace("LAPTOP", c2)

        station = engine.resolve_station("LAPTOP")
        assert len(station.contact_log) == 1
        assert station.contact_log[0].mode == "SSB"

    def test_appinfo_sets_contest(self):
        """N1MM-L2-037: AppInfo sets contest name on station."""
        engine = StateEngine()
        info = StationInfo(
            contest_name="CQ-WW-CW", station_name="LAPTOP", mycall="KI7MT"
        )
        engine.handle_appinfo("LAPTOP", info)

        station = engine.resolve_station("LAPTOP")
        assert station.station_info.contest_name == "CQ-WW-CW"


# ---------------------------------------------------------------------------
# N1MM-L2-038..040: Integration (frequency + band)
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_tens_hz_to_band(self):
        """N1MM-L2-038: Tens-Hz → MHz → band pipeline."""
        freq_mhz = from_tens_hz(1407400)
        assert freq_to_band(freq_mhz) == "20m"

    def test_spot_freq_to_band(self):
        """N1MM-L2-039: Spot kHz → MHz → band pipeline."""
        freq_mhz = from_spot_freq("7030.0")
        assert freq_to_band(freq_mhz) == "40m"

    def test_edge_of_band(self):
        """N1MM-L2-040: Band edge frequency still resolves."""
        assert freq_to_band(14.0) == "20m"
        assert freq_to_band(14.35) == "20m"
        assert freq_to_band(13.99) == "unknown"
