"""n1mm-mcp — MCP server for N1MM Logger+ contest state via UDP broadcast."""

try:
    from importlib.metadata import version

    __version__ = version("n1mm-mcp")
except Exception:
    __version__ = "0.0.0-dev"
