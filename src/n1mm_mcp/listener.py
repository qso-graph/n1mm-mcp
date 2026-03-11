"""UDP listener for N1MM Logger+ broadcast messages.

Runs in a background daemon thread, parses XML, and updates the StateEngine.

Parse failure policy (Patton P1):
  - ContactInfo failures → WARNING + first 200 bytes of raw payload
  - All other message types → DEBUG (next packet will update state)
  - Per-message-type error counters maintained for diagnostics
"""

from __future__ import annotations

import logging
import os
import socket
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from .frequency import from_tens_hz
from .models import (
    Contact,
    LookupState,
    RadioState,
    ScoreState,
    Spot,
    StationInfo,
)
from .state import StateEngine

logger = logging.getLogger(__name__)

# UDP buffer size — N1MM packets are small XML, 4K is plenty
_BUFSIZE = 4096


def _bool(val: str) -> bool:
    return val.strip().lower() in ("true", "1", "yes")


def _int(val: str, default: int = 0) -> int:
    try:
        return int(val.strip())
    except (ValueError, TypeError, AttributeError):
        return default


def _text(elem: ET.Element, tag: str, default: str = "") -> str:
    child = elem.find(tag)
    if child is not None and child.text is not None:
        return child.text.strip()
    return default


def _parse_radioinfo(root: ET.Element) -> tuple[str, RadioState]:
    station = _text(root, "StationName", "DEFAULT")
    return station, RadioState(
        radio_nr=_int(_text(root, "RadioNr"), 1),
        freq_hz=_int(_text(root, "Freq")),
        tx_freq_hz=_int(_text(root, "TXFreq")),
        mode=_text(root, "Mode"),
        op_call=_text(root, "OpCall"),
        mycall=_text(root, "mycall"),
        is_running=_bool(_text(root, "IsRunning")),
        is_split=_bool(_text(root, "IsSplit")),
        is_transmitting=_bool(_text(root, "IsTransmitting")),
        is_connected=_bool(_text(root, "IsConnected")),
        antenna=_int(_text(root, "Antenna")),
        aux_antenna=_int(_text(root, "AuxAntSelected"), -1),
        aux_antenna_name=_text(root, "AuxAntSelectedName"),
        rotors=_text(root, "Rotors"),
        radio_name=_text(root, "RadioName"),
        focus_radio_nr=_int(_text(root, "FocusRadioNr"), 1),
        active_radio_nr=_int(_text(root, "ActiveRadioNr"), 1),
        is_stereo=_bool(_text(root, "IsStereo")),
        station_name=station,
        received_at=datetime.now(timezone.utc),
    )


def _parse_appinfo(root: ET.Element) -> tuple[str, StationInfo]:
    station = _text(root, "StationName", "DEFAULT")
    return station, StationInfo(
        app=_text(root, "app"),
        dbname=_text(root, "dbname"),
        contest_nr=_text(root, "contestnr"),
        contest_name=_text(root, "contestname"),
        station_name=station,
        mycall=_text(root, "mycall"),
        received_at=datetime.now(timezone.utc),
    )


def _parse_contact(root: ET.Element) -> tuple[str, Contact]:
    station = _text(root, "StationName", "DEFAULT")
    return station, Contact(
        guid=_text(root, "ID"),
        call=_text(root, "call"),
        mycall=_text(root, "mycall"),
        operator=_text(root, "operator"),
        station_name=station,
        rxfreq=_int(_text(root, "rxfreq")),
        txfreq=_int(_text(root, "txfreq")),
        band=_text(root, "band"),
        mode=_text(root, "mode"),
        snt=_text(root, "snt"),
        sntnr=_text(root, "sntnr"),
        rcv=_text(root, "rcv"),
        rcvnr=_text(root, "rcvnr"),
        exchange1=_text(root, "exchangel"),
        section=_text(root, "section"),
        comment=_text(root, "comment"),
        qth=_text(root, "qth"),
        name=_text(root, "name"),
        zone=_text(root, "zone"),
        prec=_text(root, "prec"),
        ck=_text(root, "ck"),
        country_prefix=_text(root, "countryprefix"),
        wpx_prefix=_text(root, "wpxprefix"),
        continent=_text(root, "continent"),
        gridsquare=_text(root, "gridsquare"),
        # NOTE: ismultiplierl — lowercase L, not digit 1 (N1MM documented typo)
        is_multiplier1=_int(_text(root, "ismultiplierl")),
        is_multiplier2=_int(_text(root, "ismultiplier2")),
        is_multiplier3=_int(_text(root, "ismultiplier3")),
        points=_int(_text(root, "points")),
        radio_nr=_int(_text(root, "radionr"), 1),
        run1run2=_int(_text(root, "run1run2"), 1),
        is_run_qso=_int(_text(root, "IsRunQSO")),
        is_original=_bool(_text(root, "IsOriginal", "True")),
        is_claimed_qso=_bool(_text(root, "IsClaimedQso", "True")),
        radio_interfaced=_bool(_text(root, "RadioInterfaced", "True")),
        netbios_name=_text(root, "NetBiosName"),
        networked_comp_nr=_int(_text(root, "NetworkedCompNr")),
        timestamp=_text(root, "timestamp"),
        old_timestamp=_text(root, "oldtimestamp"),
        old_call=_text(root, "oldcall"),
        contest_name=_text(root, "contestname"),
        contest_nr=_text(root, "contestnr"),
        received_at=datetime.now(timezone.utc),
    )


def _parse_spot(root: ET.Element) -> tuple[str, Spot]:
    station = _text(root, "StationName", "DEFAULT")
    return station, Spot(
        dxcall=_text(root, "dxcall"),
        frequency=_text(root, "frequency"),
        spotter_call=_text(root, "spottercall"),
        timestamp=_text(root, "timestamp"),
        action=_text(root, "action"),
        mode=_text(root, "mode"),
        comment=_text(root, "comment"),
        status=_text(root, "status"),
        status_list=_text(root, "statuslist"),
        station_name=station,
        received_at=datetime.now(timezone.utc),
    )


def _parse_score(root: ET.Element) -> tuple[str, ScoreState]:
    """Parse DynamicResults XML."""
    call = _text(root, "call")
    # DynamicResults XML lacks StationName — use call as partition key.
    # Phase 2 NOTE: In multi-op, call may be the shared contest call (e.g. K3LR)
    # across all stations, causing score state to land on a partition that
    # doesn't match RadioInfo/ContactInfo partitions. Needs StationName mapping.
    station = call

    score = ScoreState(
        contest=_text(root, "contest"),
        call=call,
        ops=_text(root, "ops"),
        score=_int(_text(root, "score")),
        timestamp=_text(root, "timestamp"),
        station_name=station,
        received_at=datetime.now(timezone.utc),
    )

    # Parse <class> attributes
    cls = root.find("class")
    if cls is not None:
        score.power = cls.get("power", "")
        score.assisted = cls.get("assisted", "")
        score.transmitter = cls.get("transmitter", "")
        score.ops_category = cls.get("ops", "")
        score.bands = cls.get("bands", "")
        score.score_mode = cls.get("mode", "")
        score.overlay = cls.get("overlay", "")

    # Parse <qth> attributes
    qth = root.find("qth")
    if qth is not None:
        score.dxcc_country = qth.get("dxcccountry", "")
        score.cq_zone = qth.get("cqzone", "")
        score.iaru_zone = qth.get("iaruzone", "")
        score.arrl_section = qth.get("arrlsection", "")
        score.grid6 = qth.get("grid6", "")

    # Parse <breakdown> QSOs per band/mode
    breakdown = root.find("breakdown")
    if breakdown is not None:
        for qso_elem in breakdown.findall("qso"):
            band_val = qso_elem.get("band", "")
            mode_val = qso_elem.get("mode", "")
            count = _int(qso_elem.text or "0")
            score.band_mode_qsos[(band_val, mode_val)] = count

    return station, score


def _parse_lookup(root: ET.Element) -> tuple[str, LookupState]:
    station = _text(root, "StationName", "DEFAULT")
    return station, LookupState(
        call=_text(root, "call"),
        gridsquare=_text(root, "gridsquare"),
        name=_text(root, "name"),
        section=_text(root, "section"),
        bearing=_text(root, "bearing"),
        distance=_text(root, "distance"),
        country_prefix=_text(root, "countryprefix"),
        wpx_prefix=_text(root, "wpxprefix"),
        continent=_text(root, "continent"),
        zone=_text(root, "zone"),
        is_multiplier1=_int(_text(root, "ismultiplierl")),
        is_multiplier2=_int(_text(root, "ismultiplier2")),
        is_multiplier3=_int(_text(root, "ismultiplier3")),
        station_name=station,
        received_at=datetime.now(timezone.utc),
    )


# Tag → (parser, error_counter_attr, is_high_consequence)
_PARSERS: dict[str, tuple[Any, str, bool]] = {
    "RadioInfo": (_parse_radioinfo, "radioinfo", False),
    "AppInfo": (_parse_appinfo, "appinfo", False),
    "contactinfo": (_parse_contact, "contactinfo", True),
    "contactreplace": (_parse_contact, "contactreplace", True),
    "contactdelete": (None, "contactdelete", True),  # special handling
    "lookupinfo": (_parse_lookup, "lookup", False),
    "spot": (_parse_spot, "spot", False),
    "dynamicresults": (_parse_score, "score", False),
}


class UDPListener:
    """Background UDP listener for N1MM broadcasts."""

    def __init__(
        self,
        state: StateEngine,
        port: int = 12060,
        bind_addr: str = "0.0.0.0",
    ) -> None:
        self.state = state
        self.port = port
        self.bind_addr = bind_addr
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.settimeout(1.0)  # allow periodic stop check
        self._sock.bind((self.bind_addr, self.port))
        logger.info("UDP listener bound to %s:%d", self.bind_addr, self.port)

        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="n1mm-udp"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._sock:
            self._sock.close()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _listen_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                data, addr = self._sock.recvfrom(_BUFSIZE)  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                raise

            self.state.record_packet()
            self._process_packet(data)

    def _process_packet(self, raw: bytes) -> None:
        # Decode with replacement for Windows-1252 characters (Patton P1)
        try:
            text = raw.decode("utf-8", errors="replace")
        except Exception:
            return

        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            # Determine message type from raw text for error counter
            self._count_parse_error(text, raw)
            return

        tag = root.tag
        parser_info = _PARSERS.get(tag)
        if parser_info is None:
            logger.debug("Unknown XML tag: %s", tag)
            return

        parser_fn, error_attr, is_high = parser_info

        try:
            if tag == "contactdelete":
                station = _text(root, "StationName", "DEFAULT")
                guid = _text(root, "ID")
                call = _text(root, "call")
                band = _text(root, "band")
                ts = _text(root, "timestamp")
                self.state.handle_contactdelete(station, guid, call, band, ts)
            elif tag == "RadioInfo":
                station, radio = parser_fn(root)
                self.state.handle_radioinfo(station, radio)
            elif tag == "AppInfo":
                station, info = parser_fn(root)
                self.state.handle_appinfo(station, info)
            elif tag in ("contactinfo", "contactreplace"):
                station, contact = parser_fn(root)
                if tag == "contactinfo":
                    self.state.handle_contactinfo(station, contact)
                else:
                    self.state.handle_contactreplace(station, contact)
            elif tag == "lookupinfo":
                station, lookup = parser_fn(root)
                self.state.handle_lookup(station, lookup)
            elif tag == "spot":
                station, spot = parser_fn(root)
                self.state.handle_spot(station, spot)
            elif tag == "dynamicresults":
                station, score = parser_fn(root)
                self.state.handle_score(station, score)
        except Exception as exc:
            setattr(
                self.state.parse_errors,
                error_attr,
                getattr(self.state.parse_errors, error_attr) + 1,
            )
            if is_high:
                logger.warning(
                    "Failed to process %s: %s (first 200 bytes: %r)",
                    tag,
                    exc,
                    raw[:200],
                )
            else:
                logger.debug("Failed to process %s: %s", tag, exc)

    def _count_parse_error(self, text: str, raw: bytes) -> None:
        """Increment parse error counter based on raw XML tag guess."""
        for tag, (_, attr, is_high) in _PARSERS.items():
            if f"<{tag}" in text or f"<{tag.lower()}" in text.lower():
                setattr(
                    self.state.parse_errors,
                    attr,
                    getattr(self.state.parse_errors, attr) + 1,
                )
                if is_high:
                    logger.warning(
                        "XML parse error for %s (first 200 bytes: %r)", tag, raw[:200]
                    )
                else:
                    logger.debug("XML parse error for %s", tag)
                return
        logger.debug("XML parse error for unknown message type")


class MockListener:
    """Mock listener for testing without N1MM (N1MM_MCP_MOCK=1)."""

    def __init__(self, state: StateEngine) -> None:
        self.state = state
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        # Inject a minimal station state for testing
        info = StationInfo(
            app="N1MM",
            dbname="mock.s3db",
            contest_nr="1",
            contest_name="CQWWCW",
            station_name="MOCK",
            mycall="N0CALL",
        )
        self.state.handle_appinfo("MOCK", info)

        radio = RadioState(
            radio_nr=1,
            freq_hz=1407400,
            tx_freq_hz=1407400,
            mode="CW",
            mycall="N0CALL",
            op_call="N0CALL",
            is_running=True,
            is_connected=True,
            station_name="MOCK",
            radio_name="Mock Radio",
        )
        self.state.handle_radioinfo("MOCK", radio)
        self.state.record_packet()
        logger.info("Mock listener started — station MOCK with CW on 20m")

    def stop(self) -> None:
        self._stop_event.set()
