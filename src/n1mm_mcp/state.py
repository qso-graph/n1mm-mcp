"""State engine for n1mm-mcp.

All state is partitioned by StationName (Einstein MANDATORY #2).
Each StationState holds the full contest state for one N1MM instance.

LOCK ACQUISITION ORDER (Patton P1 — HARD RULE):
    radio_lock → contact_lock → score_lock → spot_lock → lookup_lock

Any code path that needs multiple locks MUST acquire them in this order.
This prevents deadlock between the UDP listener thread (writes) and
concurrent MCP tool handlers (reads). Violation = deadlock risk.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .frequency import freq_to_band, from_mhz_str, from_tens_hz
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
        self.station_info: StationInfo = StationInfo(station_name=station_name)

        self.contact_log: list[Contact] = []
        self.contact_index: dict[str, int] = {}  # GUID → index in contact_log
        self.edit_log: deque[Contact] = deque(maxlen=100)
        self.delete_log: deque[dict[str, Any]] = deque(maxlen=100)

        self.spot_map: dict[tuple[str, str], Spot] = {}  # (dxcall, band) → Spot
        self.spot_buffer: deque[Spot] = deque(maxlen=max_spots)

        self.score_state: ScoreState | None = None
        self.lookup_state: LookupState | None = None

    def update_radio(self, radio: RadioState) -> None:
        with self.radio_lock:
            self.radio_state[radio.radio_nr] = radio

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
        band = freq_to_band(from_mhz_str(spot.frequency))
        with self.spot_lock:
            if spot.action == "delete":
                self.spot_map.pop((spot.dxcall, band), None)
            else:
                self.spot_map[(spot.dxcall, band)] = spot
            self.spot_buffer.append(spot)

    def evict_stale_spots(self) -> None:
        """Remove spots older than TTL from the spot_map (Patton P2)."""
        now = time.monotonic()
        cutoff = datetime.now(timezone.utc).timestamp() - self.spot_ttl
        with self.spot_lock:
            stale = [
                k
                for k, v in self.spot_map.items()
                if v.received_at.timestamp() < cutoff
            ]
            for k in stale:
                del self.spot_map[k]

    def update_score(self, score: ScoreState) -> None:
        with self.score_lock:
            self.score_state = score

    def update_lookup(self, lookup: LookupState) -> None:
        with self.lookup_lock:
            self.lookup_state = lookup

    def reset_contest_state(self) -> None:
        """Reset state on contest name change (Patton P0).

        Clears contacts, score, spots, mults — preserves station_info.
        """
        with self.contact_lock:
            self.contact_log.clear()
            self.contact_index.clear()
            self.edit_log.clear()
            self.delete_log.clear()
        with self.score_lock:
            self.score_state = None
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

    def handle_score(self, station_name: str, score: ScoreState) -> None:
        # dynamicresults lacks <StationName> — listener passes call as station_name.
        # Map to real station via _call_to_station (populated by RadioInfo).
        resolved = self._call_to_station.get(station_name, station_name)
        station = self._get_or_create_station(resolved)
        station.update_score(score)
        # Backfill contest_name from Score if AppInfo never arrived
        if score.contest:
            with station.radio_lock:
                if not station.station_info.contest_name:
                    station.station_info.contest_name = score.contest
                    logger.info(
                        "Contest name backfilled from Score: %s (station %s)",
                        score.contest,
                        resolved,
                    )

    def handle_lookup(self, station_name: str, lookup: LookupState) -> None:
        station = self._get_or_create_station(station_name)
        station.update_lookup(lookup)
