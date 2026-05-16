# n1mm-mcp

<!-- mcp-name: n1mm-mcp -->

MCP server for [N1MM Logger+](https://n1mm.hamdocs.com/) — live contest state via UDP broadcast.

Part of the [qso-graph](https://qso-graph.io) amateur radio MCP ecosystem.

## Install

```bash
pip install n1mm-mcp
```

## Tools (Phase 1 — 8 Composite State Views)

| Tool | Description |
|------|-------------|
| `n1mm_current_state` | Station snapshot — connection, contest, operator, radios |
| `n1mm_lookup` | Pre-log callsign (Contest-Copilot trigger) + current band/mode |
| `n1mm_contacts` | QSO log — recent contacts, edits, deletes |
| `n1mm_bandmap` | Live spots, mult targets, band activity |
| `n1mm_performance` | Score, rate, bands, run/S&P, hourly timeline |
| `n1mm_multipliers` | Mult grid, needs, value analysis |
| `n1mm_clock` | Contest timing, off-time, pacing |
| `n1mm_diagnostics` | Server health, parse errors, memory |
| `get_version_info` | Service version + upstream UDP contract version (fleet identity attestation) |

## Quick Start

1. In N1MM: **Config → Configure Ports → Broadcast Data** — enable all message types
2. N1MM broadcasts to `255.255.255.255:12060` by default

### Claude Desktop

```json
{
  "mcpServers": {
    "n1mm": {
      "command": "n1mm-mcp"
    }
  }
}
```

Or with `uvx` (no install needed):

```json
{
  "mcpServers": {
    "n1mm": {
      "command": "uvx",
      "args": ["n1mm-mcp"]
    }
  }
}
```

### Claude Code

```bash
claude mcp add n1mm-mcp -- n1mm-mcp
```

## Architecture

```
N1MM Logger+ (Windows)
    │ UDP broadcast (port 12060, XML)
    ▼
n1mm-mcp (Python, any OS on same LAN)
    ├── UDP Listener Thread (background)
    ├── State Engine (in-memory, partitioned by StationName)
    │   MCP protocol (stdio)
    ▼
AI Assistant (Claude, qsp-mcp, etc.)
```

- **Passive listener** — N1MM doesn't know we exist
- **Stream-to-state** — UDP packets → in-memory state → tool queries
- **Multi-station** — state partitioned by StationName (SO2R, multi-op)
- **Zero auth** — no credentials needed

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | `12060` | UDP listen port |
| `--transport` | `stdio` | MCP transport (`stdio` or `streamable-http`) |
| `--heartbeat-timeout` | `60` | Seconds before connection goes stale |
| `--stale-timeout` | `900` | Seconds before connection goes disconnected |
| `--max-spots` | `2000` | Maximum spots in bandmap buffer |
| `--spot-ttl` | `30` | Spot time-to-live in **minutes** |

## Testing

```bash
# Mock mode (no N1MM needed)
N1MM_MCP_MOCK=1 n1mm-mcp

# MCP Inspector
n1mm-mcp --transport streamable-http
```

## Development

```bash
git clone https://github.com/qso-graph/n1mm-mcp.git
cd n1mm-mcp
pip install -e .
N1MM_MCP_MOCK=1 n1mm-mcp
```

## License

GPL-3.0-or-later
