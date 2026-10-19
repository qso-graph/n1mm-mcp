"""Conformance with the Model Context Protocol, revision 2026-07-28.

Nothing in this project's documents required this until 2026-10-11. We documented how
to *publish* an MCP server in detail and never wrote down what makes one *valid*, which
is how a missing ``isError`` and missing annotations reached every server in the fleet.

Particular to this server:

* **Every tool really is read-only**, unlike netlogger-mcp and omiss-mcp where issue
  text claiming so was wrong. Checked here rather than assumed: this package writes
  nothing anywhere, it only listens to N1MM's UDP broadcast.
* **The ambiguous-station response had no test at all.** ``_station_error`` was reached
  from nine call sites and nothing in the suite exercised any of them, so its shape was
  free to be anything. ``TestTheStationChoice`` covers it now, and the thing it holds
  is that the station *names* survive the conversion — they are the choices the caller
  has to pick from, so a flagged error saying only "specify station_name" would be
  worse than the payload it replaced.
* **No ``certifi`` work and no issue for it**, correctly: this server makes no outbound
  HTTP call of any kind. The fleet-wide TLS fix does not apply.

Test IDs: NM-C01 onward.
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp.exceptions import ToolError

import n1mm_mcp.server as srv
from n1mm_mcp.models import RadioState
from n1mm_mcp.state import StateEngine

ANNOTATION_HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

READS_N1MM = {
    "n1mm_current_state", "n1mm_lookup", "n1mm_contacts", "n1mm_bandmap",
    "n1mm_performance", "n1mm_multipliers", "n1mm_clock", "n1mm_diagnostics",
    "n1mm_network", "n1mm_pileup", "n1mm_so2r",
}
ANSWERS_FROM_THE_PACKAGE = {"get_version_info"}


@pytest.fixture(autouse=True)
def engine():
    """A fresh state engine per test; the server memoises one otherwise."""
    srv._state = StateEngine()
    yield srv._state
    srv._state = None


def _tools() -> dict[str, object]:
    return {t.name: t for t in asyncio.run(srv.mcp.list_tools())}


def _wire(tool: object) -> dict[str, object]:
    annotations = getattr(tool, "annotations", None)
    assert annotations is not None, "tool declares no annotations"
    return annotations.model_dump(by_alias=True, exclude_none=True)


def _station(engine, name: str) -> None:
    """Register one station the way N1MM does — a RadioInfo packet.

    Uses the engine's real entry point rather than a constructor of my own; the
    first version of this file invented `apply_station`, which does not exist.
    """
    engine.handle_radioinfo(name, RadioState(
        radio_nr=1, freq_hz=int(14.025 * 100000), mode="CW", mycall="K7XX",
    ))


def _two_stations(engine) -> list[str]:
    """Two stations reporting, which is what makes station_name ambiguous."""
    for name in ("SHACK-A", "SHACK-B"):
        _station(engine, name)
    names = sorted(engine.get_station_names())
    assert len(names) == 2, f"setup did not produce an ambiguous case: {names}"
    return names


class TestToolAnnotations:
    def test_every_tool_declares_all_four_hints(self) -> None:
        """NM-C01: the defaults are pessimistic, so silence is the wrong answer."""
        for name, tool in _tools().items():
            wire = _wire(tool)
            for hint in ANNOTATION_HINTS:
                assert hint in wire, f"{name} omits {hint}; got {sorted(wire)}"

    def test_every_tool_is_read_only_and_that_was_checked(self) -> None:
        """NM-C02: true here, unlike the two servers before it in the sweep."""
        for name, tool in _tools().items():
            wire = _wire(tool)
            assert wire["readOnlyHint"] is True, name
            assert wire["destructiveHint"] is False, name

    def test_idempotent_despite_a_moving_answer(self) -> None:
        """NM-C03: a contest in progress changes the answer, not the state.

        Two identical calls a second apart can differ because N1MM keeps
        broadcasting. `idempotentHint` is about the tool not changing anything, so it
        stays true — recorded as a test because it is the kind of thing a later reader
        would "correct" to false.
        """
        for name, tool in _tools().items():
            assert _wire(tool)["idempotentHint"] is True, name

    def test_open_world_is_read_per_tool(self) -> None:
        """NM-C04: eleven read N1MM; one answers from the wheel."""
        tools = _tools()
        assert set(tools) == READS_N1MM | ANSWERS_FROM_THE_PACKAGE
        for name in READS_N1MM:
            assert _wire(tools[name])["openWorldHint"] is True, name
        for name in ANSWERS_FROM_THE_PACKAGE:
            assert _wire(tools[name])["openWorldHint"] is False, name


class TestTheStationChoice:
    """Nine call sites, and before this file, no test touched any of them.

    ``_station_error`` returned a *successful* result carrying
    ``error: "multiple_stations"`` and a ``stations`` list. It is now raised, and what
    these tests hold is that the names survive: they are the choices, and an error
    that said only "specify station_name" would be less useful than the dict it
    replaced.
    """

    def test_it_is_flagged(self, engine) -> None:
        """NM-C10: a refusal, not an answer."""
        _two_stations(engine)
        with pytest.raises(ToolError):
            srv.n1mm_current_state()

    def test_the_station_names_are_in_the_message(self, engine) -> None:
        """NM-C11: the whole reason the old payload existed."""
        names = _two_stations(engine)
        with pytest.raises(ToolError) as caught:
            srv.n1mm_current_state()
        message = str(caught.value)
        for name in names:
            assert name in message, f"{name} is a valid choice and is not offered"
        assert "station_name" in message

    def test_naming_a_station_resolves_it(self, engine) -> None:
        """NM-C12: the control — the refusal has to be escapable the way it says."""
        names = _two_stations(engine)
        answer = srv.n1mm_current_state(station_name=names[0])
        assert isinstance(answer, dict)
        assert "error" not in answer

    def test_one_station_needs_no_choice(self, engine) -> None:
        """NM-C13: the refusal fires on ambiguity, not on every call."""
        _station(engine, "SOLO")
        answer = srv.n1mm_current_state()
        assert isinstance(answer, dict)
        assert "error" not in answer


class TestBadInputIsFlagged:
    def test_an_out_of_range_window_is_an_error(self, engine) -> None:
        """NM-C20: was error: "invalid_window" in a successful result."""
        _station(engine, "SOLO")
        for bad in (1, 4, 1441, 5000):
            with pytest.raises(ToolError, match="window_minutes must be 5 to 1440"):
                srv.n1mm_pileup(window_minutes=bad)

    def test_a_valid_window_is_a_successful_call(self, engine) -> None:
        """NM-C21: the control."""
        _station(engine, "SOLO")
        assert "qsos" in srv.n1mm_pileup(window_minutes=15)


class TestNoErrorDictsRemain:
    def test_the_source_returns_no_error_payloads(self) -> None:
        """NM-C30: the conversion is complete, not partial.

        Checked against the source because a test that called every tool in every
        failing configuration would miss the one path nobody thought of — which is
        exactly what happened to the nine station-choice sites.
        """
        import pathlib

        src = pathlib.Path(srv.__file__).parent
        offenders = [
            f"{py.name}:{i}: {line.strip()}"
            for py in src.rglob("*.py")
            for i, line in enumerate(py.read_text().splitlines(), 1)
            if '"error":' in line or "'error':" in line
        ]
        assert not offenders, "error payloads remain:\n" + "\n".join(offenders)


class TestVersionInfoShape:
    def test_it_matches_the_shape_the_fleet_returns(self) -> None:
        """NM-C40: the convention that drifted because nobody asserted it."""
        info = srv.get_version_info()
        assert info["service_name"] == "n1mm-mcp"
        assert info["service_version"]
        assert info["spec_version"]


class TestRegistration:
    def test_the_twelve_tools_a_client_sees(self) -> None:
        """NM-C50: calling a function directly is not proof a client can."""
        assert set(_tools()) == READS_N1MM | ANSWERS_FROM_THE_PACKAGE
