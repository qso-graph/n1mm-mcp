"""State engine for n1mm-mcp.

All state is partitioned by StationName (Einstein MANDATORY #2).
Each StationState holds the full contest state for one N1MM instance.

LOCK ACQUISITION ORDER (Patton P1 — HARD RULE):
    radio_lock → contact_lock → score_lock → spot_lock → lookup_lock

Any code path that needs multiple locks MUST acquire them in this order.
StateEngine's _scores_lock and _stations_lock are never held while a station lock is
taken: score_view() copies what it needs under each lock in turn.
This prevents deadlock between the UDP listener thread (writes) and
concurrent MCP tool handlers (reads). Violation = deadlock risk.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .frequency import freq_to_band, from_spot_freq
from .models import (
    Contact,
    LookupState,
    RadioState,
    ScoreState,
    Spot,
    StationInfo,
)

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_HEARTBEAT_TIMEOUT = 60  # seconds → stale
DEFAULT_STALE_TIMEOUT = 900  # seconds → disconnected (15 min)
DEFAULT_SPOT_TTL = 1800  # seconds (30 min)
DEFAULT_MAX_SPOTS = 2000
DEFAULT_MAX_RADIO_EVENTS = 50000  # RadioInfo history for SO2R timing (#9)


@dataclass
class ParseErrors:
    """Per-message-type parse error counters (Patton P1)."""

    radioinfo: int = 0
    contactinfo: int = 0
    contactreplace: int = 0
    contactdelete: int = 0
    spot: int = 0
    score: int = 0
    lookup: int = 0
    appinfo: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "radioinfo": self.radioinfo,
            "contactinfo": self.contactinfo,
            "contactreplace": self.contactreplace,
            "contactdelete": self.contactdelete,
            "spot": self.spot,
            "score": self.score,
            "lookup": self.lookup,
            "appinfo": self.appinfo,
        }


class StationState:
    """State for one N1MM station (identified by StationName)."""

    def __init__(
        self,
        station_name: str,
        max_spots: int = DEFAULT_MAX_SPOTS,
        spot_ttl: int = DEFAULT_SPOT_TTL,
    ) -> None:
        self.station_name = station_name
        self.max_spots = max_spots
        self.spot_ttl = spot_ttl

        # Locks — acquisition order: radio → contact → score → spot → lookup
        self.radio_lock = threading.Lock()
        self.contact_lock = threading.Lock()
        self.score_lock = threading.Lock()
        self.spot_lock = threading.Lock()
        self.lookup_lock = threading.Lock()

        # State objects
        self.radio_state: dict[int, RadioState] = {}  # keyed by RadioNr (1, 2)
        # Every RadioInfo, oldest first, for SO2R timing (#9). Bounded.
        self.radio_events: deque[RadioState] = deque(maxlen=DEFAULT_MAX_RADIO_EVENTS)
        self.station_info: StationInfo = StationInfo(station_name=station_name)

        self.contact_log: list[Contact] = []
        self.contact_index: dict[str, int] = {}  # GUID → index in contact_log
        self.edit_log: deque[Contact] = deque(maxlen=100)
        self.delete_log: deque[dict[str, Any]] = deque(maxlen=100)

        self.spot_map: dict[tuple[str, str], Spot] = {}  # (dxcall, band) → Spot
        self.spot_buffer: deque[Spot] = deque(maxlen=max_spots)

        self.lookup_state: LookupState | None = None

    def update_radio(self, radio: RadioState) -> None:
        with self.radio_lock:
            self.radio_state[radio.radio_nr] = radio
            self.radio_events.append(radio)

    def snapshot(self) -> dict[str, Any]:
        """Copies of the radio and contact state, for analysis outside the locks (#9).

        Deleted contacts are left out of contacts."""
        with self.radio_lock:
            radios = dict(self.radio_state)
            events = list(self.radio_events)
            info = self.station_info
        with self.contact_lock:
            deleted = {d["guid"] for d in self.delete_log if d.get("guid")}
            contacts = [c for c in self.contact_log if not (c.guid and c.guid in deleted)]
        return {
            "station_name": self.station_name,
            "info": info,
            "radios": radios,
            "radio_events": events,
            "contacts": contacts,
        }

    def update_station_info(self, info: StationInfo) -> None:
        with self.radio_lock:
            self.station_info = info

    def add_contact(self, contact: Contact) -> None:
        with self.contact_lock:
            idx = len(self.contact_log)
            self.contact_log.append(contact)
            if contact.guid:
                self.contact_index[contact.guid] = idx

    def replace_contact(self, contact: Contact) -> None:
        with self.contact_lock:
            self.edit_log.append(contact)
            if contact.guid and contact.guid in self.contact_index:
                idx = self.contact_index[contact.guid]
                self.contact_log[idx] = contact

    def delete_contact(self, guid: str, call: str, band: str, ts: str) -> None:
        with self.contact_lock:
            self.delete_log.append(
                {"guid": guid, "call": call, "band": band, "timestamp": ts}
            )
            # Don't remove from contact_log — mark as deleted via delete_log

    def add_spot(self, spot: Spot) -> None:
        band = freq_to_band(from_spot_freq(spot.frequency))
        with self.spot_lock:
            if spot.action == "delete":
                self.spot_map.pop((spot.dxcall, band), None)
            else:
                self.spot_map[(spot.dxcall, band)] = spot
            self.spot_buffer.append(spot)

    def evict_stale_spots(self) -> None:
        """Remove spots older than TTL from the spot_map (Patton P2)."""
        cutoff = datetime.now(timezone.utc).timestamp() - self.spot_ttl
        with self.spot_lock:
            stale = [
                k
                for k, v in self.spot_map.items()
                if v.received_at.timestamp() < cutoff
            ]
            for k in stale:
                del self.spot_map[k]

    def calls(self) -> set[str]:
        """The contest callsigns this station uses: from AppInfo, RadioInfo and contacts."""
        with self.radio_lock:
            found = {self.station_info.mycall} | {r.mycall for r in self.radio_state.values()}
        with self.contact_lock:
            if self.contact_log:
                found.add(self.contact_log[-1].mycall)
        return {c.strip().upper() for c in found if c and c.strip()}

    def contest_name(self) -> str:
        with self.radio_lock:
            return self.station_info.contest_name

    def observed_qsos(self) -> int:
        with self.contact_lock:
            return len(self.contact_log)

    def update_lookup(self, lookup: LookupState) -> None:
        with self.lookup_lock:
            self.lookup_state = lookup

    def reset_contest_state(self) -> None:
        """Reset state on contest name change (Patton P0).

        Clears contacts, spots, mults and the radio history — preserves station_info. The score is held per
        contest call (StateEngine) and is only shown for the contest it reports.
        """
        with self.radio_lock:
            self.radio_events.clear()
        with self.contact_lock:
            self.contact_log.clear()
            self.contact_index.clear()
            self.edit_log.clear()
            self.delete_log.clear()
        with self.spot_lock:
            self.spot_map.clear()
            self.spot_buffer.clear()
        with self.lookup_lock:
            self.lookup_state = None
        logger.info(
            "Contest state reset for station %s (contest name changed)",
            self.station_name,
        )


class StateEngine:
    """Top-level state manager — partitions by StationName (Einstein MANDATORY #2)."""

    def __init__(
        self,
        heartbeat_timeout: int = DEFAULT_HEARTBEAT_TIMEOUT,
        stale_timeout: int = DEFAULT_STALE_TIMEOUT,
        max_spots: int = DEFAULT_MAX_SPOTS,
        spot_ttl: int = DEFAULT_SPOT_TTL,
    ) -> None:
        self.heartbeat_timeout = heartbeat_timeout
        self.stale_timeout = stale_timeout
        self.max_spots = max_spots
        self.spot_ttl = spot_ttl

        self._stations_lock = threading.Lock()
        self._stations: dict[str, StationState] = {}

        # Callsign → StationName mapping (fixes dynamicresults partition split).
        # RadioInfo carries mycall + StationName; dynamicresults only has call.
        # This map lets us route Score packets to the correct station.
        self._call_to_station: dict[str, str] = {}

        # Scores, by contest call (#12). DynamicResults has no StationName: at a multi-op
        # station every PC shares one call, so the score belongs to the call, and each
        # station on that call shows it, labelled as shared.
        self._scores_lock = threading.Lock()
        self._scores: dict[str, ScoreState] = {}

        self.parse_errors = ParseErrors()
        self.packets_received: int = 0
        self.last_packet_at: datetime | None = None
        self.started_at: datetime = datetime.now(timezone.utc)

    def _get_or_create_station(self, station_name: str) -> StationState:
        with self._stations_lock:
            if station_name not in self._stations:
                self._stations[station_name] = StationState(
                    station_name=station_name,
                    max_spots=self.max_spots,
                    spot_ttl=self.spot_ttl,
                )
                logger.info("New station detected: %s", station_name)
            return self._stations[station_name]

    def record_packet(self) -> None:
        self.packets_received += 1
        self.last_packet_at = datetime.now(timezone.utc)

    def get_station_names(self) -> list[str]:
        with self._stations_lock:
            return list(self._stations.keys())

    def resolve_station(self, station_name: str | None) -> StationState | None:
        """Resolve station_name param per Einstein MANDATORY #2.

        - If station_name given, return that station (or None if not found)
        - If omitted with 1 station, return it
        - If omitted with 0 or 2+ stations, return None (caller handles error)
        """
        with self._stations_lock:
            if station_name is not None:
                # Direct match first, then try callsign→station mapping
                station = self._stations.get(station_name)
                if station is None:
                    resolved = self._call_to_station.get(station_name)
                    if resolved:
                        station = self._stations.get(resolved)
                return station
            if len(self._stations) == 1:
                return next(iter(self._stations.values()))
            return None

    def connection_status(self) -> str:
        """Three-state connection model (Patton P1)."""
        if self.last_packet_at is None:
            return "disconnected"
        age = (datetime.now(timezone.utc) - self.last_packet_at).total_seconds()
        if age <= self.heartbeat_timeout:
            return "connected"
        if age <= self.stale_timeout:
            return "stale"
        return "disconnected"

    def handle_appinfo(self, station_name: str, info: StationInfo) -> None:
        station = self._get_or_create_station(station_name)
        # Contest name change detection (Patton P0)
        with station.radio_lock:
            old_contest = station.station_info.contest_name
        if old_contest and old_contest != info.contest_name:
            logger.info(
                "Contest change detected: %s → %s (station %s)",
                old_contest,
                info.contest_name,
                station_name,
            )
            station.reset_contest_state()
        station.update_station_info(info)

    def handle_radioinfo(self, station_name: str, radio: RadioState) -> None:
        station = self._get_or_create_station(station_name)
        station.update_radio(radio)
        # Register mycall → StationName so Score packets route correctly
        if radio.mycall:
            self._call_to_station[radio.mycall] = station_name

    def handle_contactinfo(self, station_name: str, contact: Contact) -> None:
        station = self._get_or_create_station(station_name)
        station.add_contact(contact)

    def handle_contactreplace(self, station_name: str, contact: Contact) -> None:
        station = self._get_or_create_station(station_name)
        station.replace_contact(contact)

    def handle_contactdelete(
        self, station_name: str, guid: str, call: str, band: str, timestamp: str
    ) -> None:
        station = self._get_or_create_station(station_name)
        station.delete_contact(guid, call, band, timestamp)

    def handle_spot(self, station_name: str, spot: Spot) -> None:
        station = self._get_or_create_station(station_name)
        station.add_spot(spot)
        # Lazy eviction — run periodically, not on every spot
        if self.packets_received % 100 == 0:
            station.evict_stale_spots()

    def handle_score(self, call: str, score: ScoreState) -> None:
        """Store a score under its contest call (#12).

        If no station is known to use the call yet (no AppInfo, RadioInfo or contact
        from it), a station named after the call holds it, so a lone score is still seen."""
        call = (call or "").strip().upper()
        if not call:
            return
        with self._scores_lock:
            self._scores[call] = score
        with self._stations_lock:
            stations = list(self._stations.values())
        users = [st for st in stations if call in st.calls()]
        if not users:
            st = self._get_or_create_station(call)
            with st.radio_lock:
                if not st.station_info.mycall:
                    st.station_info.mycall = call
            users = [st]
        # Backfill contest_name from Score if AppInfo never arrived
        if score.contest:
            for st in users:
                with st.radio_lock:
                    if not st.station_info.contest_name:
                        st.station_info.contest_name = score.contest
                        logger.info(
                            "Contest name backfilled from Score: %s (station %s)",
                            score.contest,
                            st.station_name,
                        )

    def score_view(self, station: StationState) -> dict[str, Any] | None:
        """The score for a station's contest call, or None (#12).

        Returns score, call, stations (every station on that call) and observed_qsos
        (contacts seen from all of them). A score for a different contest than the
        station's is not returned."""
        calls = station.calls()
        with self._scores_lock:
            found = [(c, self._scores[c]) for c in sorted(calls) if c in self._scores]
        if not found:
            return None
        call, score = max(found, key=lambda f: f[1].received_at)
        contest = station.contest_name()
        if contest and score.contest and contest != score.contest:
            return None
        with self._stations_lock:
            stations = list(self._stations.values())
        sharing = [st for st in stations if call in st.calls()]
        return {
            "score": score,
            "call": call,
            "stations": sorted(st.station_name for st in sharing),
            "observed_qsos": sum(st.observed_qsos() for st in sharing),
        }

    def handle_lookup(self, station_name: str, lookup: LookupState) -> None:
        station = self._get_or_create_station(station_name)
        station.update_lookup(lookup)
