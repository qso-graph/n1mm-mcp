<!-- mcp-name: io.github.qso-graph/n1mm-mcp -->
# n1mm-mcp

[![PyPI](https://img.shields.io/pypi/v/n1mm-mcp?label=PyPI&color=blue)](https://pypi.org/project/n1mm-mcp/)
[![MCP Registry](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fregistry.modelcontextprotocol.io%2Fv0%2Fservers%3Fsearch%3Dio.github.qso-graph%2Fn1mm-mcp%26version%3Dlatest&query=%24.servers%5B0%5D.server.version&label=MCP%20Registry&color=blue)](https://registry.modelcontextprotocol.io/v0/servers?search=io.github.qso-graph/n1mm-mcp&version=latest)

MCP server for [N1MM Logger+](https://n1mm.hamdocs.com/): live contest state — station, QSOs, bandmap, score and rate, multipliers, and contest clock — through any MCP-compatible AI assistant.

Data from N1MM Logger+'s UDP broadcasts on your local network. Part of the [qso-graph](https://qso-graph.io/) project. **No authentication required.**

## Install

```bash
uvx n1mm-mcp            # run it; nothing to install
```

## Tools

| Tool | Description | Key Parameters |
|------|-------------|----------------|
| `n1mm_current_state` | Station snapshot: connection, contest, operator, radios | station_name |
| `n1mm_lookup` | The callsign being entered (pre-log) plus current band and mode | station_name |
| `n1mm_contacts` | QSO log: recent contacts, edits and deletes | count, since, band, mode, call_pattern |
| `n1mm_bandmap` | Live spots, multiplier targets, band activity | band, mode, callsign, mults_only |
| `n1mm_performance` | Score, rate, bands, run/S&P, hourly timeline | band, mode |
| `n1mm_multipliers` | Multiplier grid, needs, value analysis | band |
| `n1mm_clock` | Contest timing, off-time, pacing | duration_hours, target_score, target_qsos, min_gap_minutes |
| `n1mm_diagnostics` | Server health, parse errors, memory | station_name |
| `n1mm_so2r` | Two radios: each radio now, transmit/receive focus, same-band warning, transmit time and minutes per band, focus swaps, QSOs per radio and while the other radio runs | station_name |
| `n1mm_network` | Every networked station: operator, radios, rate, idle time, band, shared score per contest call, stations sharing a band and mode, QSOs per operator | — |
| `n1mm_pileup` | DXpedition pileup: rate, unique calls, dupes, continents and countries calling, split, dead air | window_minutes |
| `get_version_info` | Service version + upstream spec version (fleet identity attestation) | — |

Every tool except `n1mm_network` (which covers all stations) takes an optional `station_name` for multi-station setups.

Everything comes from N1MM's UDP broadcasts; n1mm-mcp never talks to a radio. N1MM reports transmitting only when it keys the radio itself (macros, its CW keyer), so a paddle or microphone PTT doesn't count as transmit time in `n1mm_so2r`.

## What is N1MM Logger+?

N1MM Logger+ is a Windows contest logger. It can broadcast its state over UDP: contacts, spots, radio info and score. n1mm-mcp listens to those broadcasts and keeps the contest state in memory, so an assistant can answer questions about it. N1MM doesn't know it's there.

```
N1MM Logger+ (Windows)
    │ UDP broadcast (port 12060, XML)
    ▼
n1mm-mcp (Python: the same PC, or any OS on the LAN)
    ├── UDP listener (background)
    ├── State engine (in memory, per StationName)
    │   MCP protocol (stdio)
    ▼
AI assistant
```

## Quick Start

### Turn on N1MM's broadcasts

1. In N1MM: **Config → Configure Ports → Broadcast Data**, and enable all message types.
2. Set the destination to `127.0.0.1:12060`, N1MM's address for "this PC". n1mm-mcp listens there
   by default, and nothing outside the PC can reach it.

#### N1MM on another PC

Run n1mm-mcp with `--bind 0.0.0.0` (every network interface) or `--bind <this PC's LAN address>`,
and point N1MM at it: this PC's address (`192.168.1.20:12060`), or your subnet's broadcast address
(`192.168.1.255:12060`) to reach every PC on it. N1MM accepts several destinations separated by
spaces. Don't use `255.255.255.255`: N1MM's own documentation warns that it risks broadcasting to
the internet ([N1MM: External UDP Broadcasts](https://n1mmwp.hamdocs.com/appendices/external-udp-broadcasts/)).

Listening on the network means any device on it can send n1mm-mcp packets, so only do it on a
network you trust.

### Configure your MCP client

n1mm-mcp works with any MCP-compatible client. Add the server config and restart. The tools appear automatically.

#### Claude Desktop

Add to `claude_desktop_config.json` (`~/Library/Application Support/Claude/` on macOS, `%APPDATA%\Claude\` on Windows):

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

#### Claude Code

Add to `.claude/settings.json`:

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

#### ChatGPT Desktop

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

#### Cursor

Add to `.cursor/mcp.json` (project-level) or `~/.cursor/mcp.json` (global):

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

#### VS Code / GitHub Copilot

Add to `.vscode/mcp.json` in your workspace:

```json
{
  "servers": {
    "n1mm": {
      "command": "uvx",
      "args": ["n1mm-mcp"]
    }
  }
}
```

#### Gemini CLI

Add to `~/.gemini/settings.json` (global) or `.gemini/settings.json` (project):

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

### Ask questions

> "What's my rate over the last hour?"

> "Which multipliers do I still need on 20m?"

> "Is the station on the bandmap a new multiplier?"

> "How much off-time have I used, and am I on pace for my target?"

> "Show me the last 10 QSOs."

## CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | `12060` | UDP listen port |
| `--bind` | `127.0.0.1` | Address to listen on; `0.0.0.0` for N1MM on another PC |
| `--transport` | `stdio` | MCP transport (`stdio` or `streamable-http`) |
| `--heartbeat-timeout` | `60` | Seconds before the connection goes stale |
| `--stale-timeout` | `900` | Seconds before the connection goes disconnected |
| `--max-spots` | `2000` | Maximum spots in the bandmap buffer |
| `--spot-ttl` | `30` | Spot time-to-live in **minutes** |

## Testing Without N1MM

```bash
N1MM_MCP_MOCK=1 n1mm-mcp
```

## MCP Inspector

```bash
n1mm-mcp --transport streamable-http
```

Then open the MCP Inspector at `http://localhost:8008`.

## Development

```bash
git clone https://github.com/qso-graph/n1mm-mcp.git
cd n1mm-mcp
uv sync --group dev
uv run pytest
```

## License

GPL-3.0-or-later
