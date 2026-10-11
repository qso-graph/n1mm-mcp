"""The UDP listener's defaults and parsing are safe for packets from a network.

CodeQL py/bind-socket-all-network-interfaces: the listener bound 0.0.0.0 by default.
"""

from n1mm_mcp.listener import UDPListener
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
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]><contactinfo><call>&b;</call></contactinfo>'
    )
    state = StateEngine()
    UDPListener(state)._process_packet(bomb)
    assert state.parse_errors.contactinfo == 1
