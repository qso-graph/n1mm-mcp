"""The UDP listener's defaults and parsing are safe for packets from a network.

CodeQL py/bind-socket-all-network-interfaces: the listener bound 0.0.0.0 by default.
"""

import socket

import pytest

from n1mm_mcp.listener import UDPListener
from n1mm_mcp.server import resolve_listener
from n1mm_mcp.state import StateEngine


def test_listener_defaults_to_localhost():
    listener = UDPListener(StateEngine())
    assert listener.bind_addr == "127.0.0.1"


def test_listener_binds_where_told():
    listener = UDPListener(StateEngine(), port=0)
    listener.start()
    try:
        assert listener._sock.getsockname()[0] == "127.0.0.1"
    finally:
        listener.stop()


def test_entity_expansion_is_refused():
    """A "billion laughs" packet is dropped as a parse error, not expanded."""
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE contactinfo [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        b'<contactinfo><call>&b;</call></contactinfo>'
    )
    state = StateEngine()
    UDPListener(state)._process_packet(bomb)
    assert state.parse_errors.contactinfo == 1


# --- who may send (0.5.0) --------------------------------------------------
#
# The default bind was fixed when CodeQL flagged it
# (py/bind-socket-all-network-interfaces, above). What survived was the
# documented way to hear N1MM on another PC -- `--bind 0.0.0.0` -- and the
# sender's address being read off the socket and discarded. CodeQL cannot
# flag a value supplied at runtime, so the option and the advice outlived the
# finding about the default.
#
# One test per rule, and the planted case is the one that matters: a datagram
# from a sender not on the list must be dropped *unread*.

_RADIO = (
    b"<RadioInfo><StationName>SHACK</StationName><RadioNr>1</RadioNr>"
    b"<Freq>1405000</Freq><Mode>CW</Mode></RadioInfo>"
)


def _drain(listener, datagrams):
    """Run the real receive loop over a scripted list of (data, addr)."""

    class _Sock:
        def recvfrom(self, _n):
            if datagrams:
                return datagrams.pop(0)
            listener._stop_event.set()
            raise socket.timeout

    listener._sock = _Sock()
    listener._listen_loop()


def test_a_datagram_from_a_sender_not_on_the_list_is_dropped_unread():
    """The planted case. Nothing of it is parsed, and it is not counted as
    a packet received -- otherwise a forged flood would read as a healthy
    N1MM feed while nothing real arrived."""
    state = StateEngine()
    listener = UDPListener(state, allowed_senders=frozenset({"192.168.1.40"}))
    _drain(listener, [(_RADIO, ("192.168.1.99", 12060))])

    assert state.packets_received == 0, "a disallowed datagram was counted as received"
    assert state.get_station_names() == [], "a disallowed datagram reached the parser"
    assert state.rejected_senders()["total"] == 1
    assert state.rejected_senders()["senders"] == ["192.168.1.99"]


def test_a_datagram_from_an_allowed_sender_is_processed():
    """The same packet, from the list, must still work -- a check that drops
    everything is not a check."""
    state = StateEngine()
    listener = UDPListener(state, allowed_senders=frozenset({"192.168.1.40"}))
    _drain(listener, [(_RADIO, ("192.168.1.40", 12060))])

    assert state.packets_received == 1
    assert state.get_station_names() == ["SHACK"]
    assert state.rejected_senders()["total"] == 0


def test_the_rejected_sender_set_is_bounded():
    """A forged flood can carry a different source in every datagram; an
    uncapped set would be a memory leak anyone on the network could reach."""
    state = StateEngine()
    for i in range(200):
        state.record_rejected_sender(f"10.0.0.{i % 256}")
    r = state.rejected_senders()
    assert r["total"] == 200
    assert len(r["senders"]) == state._MAX_REJECTED_SENDERS
    assert r["more_not_listed"] is True


def test_an_empty_allow_list_is_refused_rather_than_accepting_nothing():
    with pytest.raises(ValueError, match="empty"):
        UDPListener(StateEngine(), allowed_senders=frozenset())


def test_the_default_accepts_only_this_machine():
    assert UDPListener(StateEngine()).allowed_senders == frozenset({"127.0.0.1"})


@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "", "*", "0", "::0"])
def test_every_interface_at_once_is_refused(bind):
    with pytest.raises(ValueError) as e:
        resolve_listener(bind, None)
    msg = str(e.value)
    assert "every network interface" in msg
    assert "--allow" in msg, "the refusal must say what to run instead"


def test_a_network_bind_without_allow_is_refused():
    with pytest.raises(ValueError) as e:
        resolve_listener("192.168.1.50", None)
    assert "--allow is required" in str(e.value)
    assert "no value meaning anyone" in str(e.value)


def test_a_network_bind_accepts_only_the_named_senders():
    bind, allowed = resolve_listener("192.168.1.50", ["192.168.1.40", "192.168.1.41"])
    assert bind == "192.168.1.50"
    assert allowed == frozenset({"192.168.1.40", "192.168.1.41"})
    assert "0.0.0.0" not in allowed


def test_loopback_needs_no_allow_and_is_this_machine():
    for given in ("127.0.0.1", "localhost"):
        bind, allowed = resolve_listener(given, None)
        assert bind == "127.0.0.1"
        assert allowed == frozenset({"127.0.0.1"})


def test_a_name_is_not_accepted_as_an_allowed_sender():
    """Resolving a name per datagram would make who is trusted depend on DNS
    at that moment."""
    with pytest.raises(ValueError, match="not an IP address"):
        resolve_listener("192.168.1.50", ["n1mm-pc"])


def test_the_drop_count_is_visible_in_diagnostics():
    """A listener that silently discards traffic looks like one hearing
    nothing; those need different answers from the operator."""
    import n1mm_mcp.server as srv

    state = StateEngine()
    state.record_rejected_sender("192.168.1.99")
    srv._state = state
    out = srv.n1mm_diagnostics()
    assert out["dropped_sender_not_allowed"]["total"] == 1
    assert out["dropped_sender_not_allowed"]["senders"] == ["192.168.1.99"]
