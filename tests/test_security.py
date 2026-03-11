"""Security tests for n1mm-mcp — standard qso-graph security battery.

These 6 tests gate every PyPI publish via publish.yml.
"""

import re
from pathlib import Path

SRC_DIR = Path(__file__).parent.parent / "src" / "n1mm_mcp"


def _scan(pattern: str) -> list[tuple[Path, int, str]]:
    """Scan all Python source files for a regex pattern."""
    matches = []
    for f in SRC_DIR.rglob("*.py"):
        for i, line in enumerate(f.read_text().splitlines(), 1):
            if re.search(pattern, line):
                matches.append((f, i, line.strip()))
    return matches


def test_no_print_credentials():
    matches = _scan(r"print.*(?:password|api_key|creds|secret|token)")
    assert not matches, f"Credential print found: {matches}"


def test_no_logging_credentials():
    matches = _scan(r"logging\..*(?:password|api_key|creds|secret|token)")
    assert not matches, f"Credential logging found: {matches}"


def test_no_subprocess():
    matches = _scan(r"subprocess\.|os\.system|shell\s*=\s*True")
    assert not matches, f"Subprocess/shell found: {matches}"


def test_all_urls_https():
    matches = _scan(r'http://(?!localhost|127\.0\.0\.1|::1)')
    assert not matches, f"Non-HTTPS URL found: {matches}"


def test_error_messages_safe():
    matches = _scan(r"raise\s+\w+\([^)]*(?:password|api_key|creds|secret)")
    assert not matches, f"Credentials in error message: {matches}"


def test_no_eval_exec():
    matches = _scan(r"(?:eval|exec)\s*\(")
    assert not matches, f"eval/exec found: {matches}"
