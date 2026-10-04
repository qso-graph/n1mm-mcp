# Changelog

All notable changes to `n1mm-mcp` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
