# Changelog

All notable changes to `n1mm-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

- **Three new tools for two radios, networked stations and DXpeditions** (#9).
  - `n1mm_so2r`: both radios now, N1MM's transmit and receive focus, a same-band flag, each
    radio's share of N1MM-keyed transmit time and minutes per band, focus swaps, QSOs per radio,
    and QSOs on one radio while the other was running.
  - `n1mm_network`: every networked station at once, with operator, radios, rate, minutes since
    the last QSO, minutes on the current band and band changes in the last hour, the contest score
    per call, stations sharing a band and mode, and QSOs per operator this hour against the last.
  - `n1mm_pileup`: over a chosen window, rate (5, 15, 60 minutes and the best 10), unique calls,
    dupes, QSOs by continent and top countries, band and mode, the split offset, and gaps of two
    minutes or more.
  Read from N1MM's broadcasts only; no rig is read. RadioInfo history is kept (bounded) for the
  SO2R timing and cleared when the contest changes. Deleted QSOs are left out.

## [0.1.8] — 2026-10-06

- **The score's QSO count no longer counts N1MM's total row twice** (#11). N1MM's score packet lists
  QSOs per band and mode plus a `band="total"` row; every row was summed, so 4 QSOs were reported as
  8 and `score_discrepancy` claimed QSOs were missed. The total row is used when present; the band
  rows are summed only when it isn't. Affects `n1mm_performance`, `n1mm_multipliers`,
  `n1mm_contacts` and `n1mm_clock`.
- **Multi-op: every station on a contest call shows its score** (#12). N1MM's score packet has no
  station name, so the score went to whichever station last reported that call. Scores are now
  held per contest call; each station using the call (from its AppInfo, RadioInfo or contacts)
  shows it, labelled `shared` with the stations it covers, and the missed-QSO check counts the
  contacts of all of them. A score for a different contest than the station's is not shown.
- PyPI: the Documentation link goes to this package's own page,
  https://qso-graph.io/servers/n1mm-mcp/ (qso-graph/.github#15).
- CI: the release flow (qso-graph/.github TEMPLATES.md). Work lands on `develop`; a release is a
  PR from `develop` into `main`, and merging it publishes to PyPI and the MCP Registry, verifies both
  and tags the release. CI runs on `develop` too, and PRs into `main` must come from `develop` or a
  `security/` branch.

## [0.1.7] — 2026-10-04

### Security
- **Listens on `127.0.0.1` by default** (was `0.0.0.0`, every network interface). Any device on the
  network could send it packets and feed false contest state to the assistant. For N1MM on another
  PC, run with `--bind 0.0.0.0` (or that interface's address). Found by CodeQL
  `py/bind-socket-all-network-interfaces`.
- **Incoming XML is parsed with `defusedxml`**, which refuses entity expansion and DTDs.

### Changed — action needed if N1MM runs on another PC
- The README's N1MM setup follows [N1MM's documentation](https://n1mmwp.hamdocs.com/appendices/external-udp-broadcasts/):
  `127.0.0.1:12060` for the same PC; that PC's address or the subnet broadcast (`x.x.x.255`) for
  another. It no longer says N1MM sends to `255.255.255.255`, which N1MM advises against.

## [0.1.6] — 2026-09-28

### Changed
- README in the qso-graph layout: tools with key parameters, what N1MM Logger+ is,
  client setup for Claude Desktop, Claude Code, ChatGPT, Cursor, VS Code and Gemini,
  example questions.
- `mcp-name` corrected to `io.github.qso-graph/n1mm-mcp` (the Registry checks it).

### Added (CI hygiene)
- **MCP Registry sync** — `publish.yml` now publishes to the [Official MCP Registry](https://registry.modelcontextprotocol.io)
  after each PyPI publish, using GitHub OIDC for auth. Triggered on
  `v*` tag push; no manual steps. Pattern documented in
  [qso-graph/.github/TEMPLATES.md](https://github.com/qso-graph/.github/blob/main/TEMPLATES.md).
- **Registry version badge** in README — PyPI and Registry versions
  are visible side-by-side so any drift between publishing surfaces
  is immediately apparent.
- **Release gates** — the tag must match `pyproject.toml`, and a
  `verify` job fails the release unless PyPI and the MCP Registry
  both serve the new version.
- `server.json` (`io.github.qso-graph/n1mm-mcp`).

## [0.1.5] — 2026-05-16

### Added
- New tool `get_version_info` — returns `{service_name, service_version, spec_version}`
  for fleet identity attestation. Tracks [IONIS-AI/ionis-devel#49](https://github.com/IONIS-AI/ionis-devel/issues/49).
- `__spec_version__` pinned to `n1mm-udp-v1`.
- L2 unit tests N1MM-L2-041 through N1MM-L2-045.
- `.github/workflows/ci.yml` — PR-gating CI (py3.10-3.13 matrix).

### Changed
- `__init__.py` modernized to fleet pattern (`Final` types).
- `get_version_info` complements (but does not replace) `n1mm_diagnostics`
  — diagnostics stays the canonical health probe (heartbeat, parse errors,
  memory). get_version_info is the lighter-weight identity attestation
  that succeeds even when N1MM isn't broadcasting.

## [0.1.4] — Previous release
- See git history for changes prior to the changelog being introduced.
