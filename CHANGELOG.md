# Changelog

All notable changes to `n1mm-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1] — 2026-10-26

- A release should appear on the Releases page
- Move every Node 20 action to its first Node 24 major
- The locked-dependency audit blocked every release
- Four upgrades arrived as 57 pull requests
- Nothing was auditing the lockfile
- Close every open security advisory in the lockfile
- A release is a workflow, not a merge

## [0.3.0] — 2026-10-19

The minor version moves because two things a caller may have relied on now behave
differently.

**Upgrading:** a tool that fails now returns `isError: true` instead of a successful result whose
payload carried an `error` key. Two shapes change, and the second is the one to read:

- `n1mm_pileup` with an out-of-range `window_minutes` returned
  `{"error": "invalid_window", ...}`; it now raises with the same message.
- **An ambiguous station** returned `{"error": "multiple_stations", "stations": [...]}` from nine
  call sites. It now raises, and **the station names are in the message** — they are the choices
  the caller has to pick from, so an error saying only "specify station_name" would have been
  worse than the payload it replaced. Anything reading `result["stations"]` should read the
  message, or pass `station_name` and avoid the refusal entirely.

### MCP specification 2026-07-28 (#29)

- **Tool errors are flagged `isError`.** Two error returns in `src/` arrived on the wire as
  successful results, so a client could not tell "the tool answered" from "the tool refused". The
  specification says of `CallToolResult.isError` that otherwise "the LLM would not be able to see
  that an error occurred and self-correct".
- **All 12 tools declare the four annotation hints.** Omitting them advertises a tool as
  `destructiveHint: true`, `idempotentHint: false`, `openWorldHint: true`.
- **Every tool here really is read-only**, and that was checked rather than taken from the issue —
  netlogger-mcp and omiss-mcp both carried the same claim and it was false in both. This package
  writes nothing anywhere; it listens to N1MM's UDP broadcast.
- `idempotentHint: true` even though two identical calls a second apart can differ, because a
  contest is in progress and N1MM keeps broadcasting. The hint is about the tool not changing
  state, not about the answer being stable. There is a test saying so, because it is the kind of
  thing a later reader would "correct".
- `openWorldHint: true` for the eleven tools that read N1MM, and the reasoning is recorded in the
  code so it can be revisited rather than rediscovered: N1MM is another program, outside this
  process, whose contents are a live contest log we neither control nor can enumerate. It is not
  the open internet — UDP on the local network — but the specification's distinction is a closed
  domain against an open one, and a contest in progress is not closed. `get_version_info` is
  `false`; it opens no socket.
- **The ambiguous-station path had no test at all** before this. Nine call sites reached
  `_station_error` and nothing in the suite exercised any of them, so its shape was free to be
  anything. `tests/test_mcp_conformance.py` covers it from both sides now: the refusal is flagged
  and carries every valid station name, and naming one resolves it.
- Seven falsifications, every one caught — including the refusal keeping its flag but dropping the
  names, which is the failure that would have quietly made the tool less useful than before.
- One check reads the source rather than calling tools: no `"error":` payload may remain anywhere
  in the package. A test that called every tool in every failing configuration would miss the path
  nobody thought of, which is exactly what happened to the nine station-choice sites.

### Lint (#28, qso-graph-devel#70)

- **`E501` is adopted.** It reported **31 lines** and not one was a defect — the finding, not an
  argument against enforcing it. The rules that do find defects (`F`, `I`, mypy strict) went in
  first, which is why this waited.
- **No line is exempt**, and none needed to be: there is no `# noqa: E501` in the repo. Most of
  the 31 were test fixtures calling `handle_appinfo` / `handle_contactinfo` with long keyword
  lists, which wrap at commas with every value intact.
- **Nothing moved on the wire.** Every tool's description and `inputSchema` was dumped through a
  real client before and after: byte-identical. Worth checking rather than assuming — netlogger-
  mcp's E501 pass did change two parameter descriptions, because an `Args:` line was reflowed
  there.
- Falsified: a long line planted in `src/` and another in `tests/`, both caught.

### Not applicable here

- **No `certifi` work and no issue for it.** This server makes no outbound HTTP call of any kind,
  so qso-graph-devel#73 does not apply. Verified rather than assumed.

## [0.2.1] — 2026-10-11

- **`n1mm_so2r` says what span its timing covers** (#21). `timing` now carries `from_utc`, the
  timestamp of the oldest RadioInfo packet still held, and `truncated` with a sentence explaining
  it. N1MM sends a RadioInfo packet per radio every ten seconds plus one on every change, so two
  radios fill the 50,000-packet history in roughly 40 to 70 hours and the oldest then drop off.
  Transmit share, minutes per band and focus swaps were computed over whatever was left, and
  nothing in the output said so — a share read at hour 40 of a 48-hour contest looked like the
  whole contest. `truncated` is reported when the history is full rather than when a drop is
  observed, because from here those are the same thing, and erring towards "these figures are
  partial" is the safe direction for a number somebody reads as a total.

- **ruff and mypy run in CI** (qso-graph-devel#66), as a job the `ci-all-green` gate requires.
  Settings follow `adif-mcp`, the reference for every qso-graph Python repo, rather than a style of
  this repo's own. They run once rather than per Python version: both read the source, and neither
  answer changes with the interpreter.
- `n1mm_so2r`'s transmit and per-band times are kept in `defaultdict(float)` rather than `Counter`.
  They accumulate seconds, and a `Counter` types its values as integers; the `most_common()` call
  that was the reason for reaching for one is written out as the sort it performs, which orders the
  same way for ties.
- `evict_stale_spots` no longer reads the monotonic clock it never used; it compares against a
  wall-clock cutoff.
- Nine unused imports removed, `ScoreState.band_mode_qsos` says what it holds, `_score_view` and
  the spot list name their types, and the listener a run chooses is one name declared to be either
  kind rather than two branch-local imports a checker reads as a reassignment.
- `E501` is deferred rather than adopted (qso-graph-devel#70): what it reports in these repos are
  widths, not defects, and some lines are long because they name a publisher's field exactly.
- **`fastmcp` is bounded: `>=4.0,<5`** (qso-graph-devel#60). It was `>=3.0` with no upper bound, and
  these servers are run with `uvx`, which resolves fresh — so a `fastmcp` 5.0 would have reached
  every user automatically, before anything here had been run against it. The floor rises to 4.0
  because that is what is actually tested: every lock in the fleet held a 4.x, and nothing in CI
  has ever exercised 3.x. A claim of 3.x support that no test backs is not support.
- `fastmcp` is locked at 4.1.0, the current release, so CI runs against what a new install gets.
- **The published contact is `maintainers@qso-graph.io`** (qso-graph-devel#69). The `authors` field
  carried a personal address, and that field is what PyPI shows on the package page. Everything in
  qso-graph is open source and open to contribution, so the contact is the project's.

## [0.2.0] — 2026-10-06

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
