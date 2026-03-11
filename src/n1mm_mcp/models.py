"""Dataclasses for N1MM UDP message types.

NOTE: The field <ismultiplierl> in N1MM ContactInfo uses a lowercase L,
not the digit 1. This is a documented typo in N1MM's source code.
Do NOT "fix" this — it must match the XML tag exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class RadioState:
    """Current state of one radio (from RadioInfo XML)."""

    radio_nr: int = 1
    freq_hz: int = 0  # tens of Hz raw value
    tx_freq_hz: int = 0
    mode: str = ""
    op_call: str = ""
    mycall: str = ""
    is_running: bool = False
    is_split: bool = False
    is_transmitting: bool = False
    is_connected: bool = False
    antenna: int = 0
    aux_antenna: int = -1
    aux_antenna_name: str = ""
    rotors: str = ""
    radio_name: str = ""
    focus_radio_nr: int = 1
    active_radio_nr: int = 1
    is_stereo: bool = False
    station_name: str = ""
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class StationInfo:
    """Contest and station metadata (from AppInfo XML)."""

    app: str = ""
    dbname: str = ""
    contest_nr: str = ""
    contest_name: str = ""
    station_name: str = ""
    mycall: str = ""
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Contact:
    """A logged QSO (from ContactInfo XML)."""

    # Identity
    guid: str = ""
    call: str = ""
    mycall: str = ""
    operator: str = ""
    station_name: str = ""

    # Frequency / band
    rxfreq: int = 0  # tens of Hz
    txfreq: int = 0
    band: str = ""
    mode: str = ""

    # Exchange
    snt: str = ""
    sntnr: str = ""
    rcv: str = ""
    rcvnr: str = ""
    exchange1: str = ""
    section: str = ""
    comment: str = ""
    qth: str = ""
    name: str = ""
    zone: str = ""
    prec: str = ""
    ck: str = ""

    # Geography
    country_prefix: str = ""
    wpx_prefix: str = ""
    continent: str = ""
    gridsquare: str = ""

    # Scoring
    # NOTE: ismultiplierl — lowercase L, not digit 1 (N1MM typo, do NOT fix)
    is_multiplier1: int = 0
    is_multiplier2: int = 0
    is_multiplier3: int = 0
    points: int = 0

    # Radio / operating
    radio_nr: int = 1
    run1run2: int = 1
    is_run_qso: int = 0
    is_original: bool = True
    is_claimed_qso: bool = True
    radio_interfaced: bool = True
    netbios_name: str = ""
    networked_comp_nr: int = 0

    # Timestamps
    timestamp: str = ""  # N1MM QSO time (may be retrospective)
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Edit tracking
    old_timestamp: str = ""
    old_call: str = ""

    # Contest
    contest_name: str = ""
    contest_nr: str = ""


@dataclass
class Spot:
    """A bandmap spot (from Spot XML)."""

    dxcall: str = ""
    frequency: str = ""  # MHz string from N1MM
    spotter_call: str = ""
    timestamp: str = ""
    action: str = ""  # "add" or "delete"
    mode: str = ""
    comment: str = ""
    status: str = ""
    status_list: str = ""
    station_name: str = ""
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ScoreState:
    """Current contest score (from DynamicResults XML)."""

    contest: str = ""
    call: str = ""
    ops: str = ""
    score: int = 0
    timestamp: str = ""

    # Class attributes
    power: str = ""
    assisted: str = ""
    transmitter: str = ""
    ops_category: str = ""
    bands: str = ""
    score_mode: str = ""
    overlay: str = ""

    # QTH
    dxcc_country: str = ""
    cq_zone: str = ""
    iaru_zone: str = ""
    arrl_section: str = ""
    grid6: str = ""

    # Per-band breakdown: {("160", "CW"): 5, ("80", "CW"): 23, ...}
    band_mode_qsos: dict = field(default_factory=dict)

    station_name: str = ""
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class LookupState:
    """Pre-log callsign lookup (from LookupInfo XML — same structure as ContactInfo)."""

    call: str = ""
    gridsquare: str = ""
    name: str = ""
    section: str = ""
    bearing: str = ""
    distance: str = ""
    country_prefix: str = ""
    wpx_prefix: str = ""
    continent: str = ""
    zone: str = ""
    is_multiplier1: int = 0
    is_multiplier2: int = 0
    is_multiplier3: int = 0
    station_name: str = ""
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
