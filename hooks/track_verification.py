"""
PostToolUse hook.

Tracks when Claude uses tools that can count as factual verification evidence.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from common import (
    get_input,
    get_state_dir,
    has_marker,
    load_config,
    output_allow,
    set_marker,
)


READLIKE_BASH_PATTERNS = [
    r"\bcat\b",
    r"\btype\b",
    r"\bget-content\b",
    r"\bsed\b",
    r"\bhead\b",
    r"\btail\b",
    r"\bselect-string\b",
    r"\brg\b",
    r"\bgrep\b",
    r"\bgit\s+show\b",
    r"\bgit\s+log\b",
    r"\bgit\s+diff\b",
    r"\bls\b",
    r"\bdir\b",
]

WEB_BASH_PATTERNS = [
    r"\bcurl\b",
    r"\bwget\b",
    r"\binvoke-webrequest\b",
]


def first_nonempty(data: dict, keys: list[str]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def get_tool_name(data: dict) -> str:
    name = first_nonempty(data, ["tool_name", "toolName", "tool"])
    if name:
        return name
    payload = data.get("payload")
    if isinstance(payload, dict):
        return first_nonempty(payload, ["tool_name", "toolName", "tool"])
    return ""


def get_tool_input(data: dict) -> dict:
    tool_input = data.get("tool_input")
    if isinstance(tool_input, dict):
        return tool_input
    payload = data.get("payload")
    if isinstance(payload, dict):
        payload_input = payload.get("tool_input")
        if isinstance(payload_input, dict):
            return payload_input
    raw_input = data.get("input")
    if isinstance(raw_input, dict):
        return raw_input
    return {}


def set_verification_marker(state_dir, tool_name: str, source_label: str, domain: str = "") -> None:
    set_marker(state_dir, "fact_verification_attempted", tool_name)
    set_marker(state_dir, "fact_verification_satisfied", source_label)
    set_marker(state_dir, "fact_verification_last_tool", tool_name)
    set_marker(state_dir, "fact_verification_last_source", source_label)
    if domain:
        set_marker(state_dir, "fact_verification_last_domain", domain)


def is_trusted_mcp_tool(tool_name: str, config: dict) -> bool:
    if not tool_name.startswith("mcp__"):
        return False
    patterns = config.get("trusted_mcp_patterns") or []
    return any(re.search(pattern, tool_name, re.IGNORECASE) for pattern in patterns)


def track_bash(tool_input: dict, state_dir) -> None:
    command = first_nonempty(tool_input, ["command", "description"])
    if not command:
        return
    lowered = command.lower()

    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in WEB_BASH_PATTERNS):
        set_verification_marker(state_dir, "Bash", f"Bash web fetch: {command[:200]}")
        return

    if any(re.search(pattern, lowered, re.IGNORECASE) for pattern in READLIKE_BASH_PATTERNS):
        set_verification_marker(state_dir, "Bash", f"Bash read command: {command[:200]}")


def track_read(tool_input: dict, state_dir) -> None:
    file_path = first_nonempty(tool_input, ["file_path", "path"])
    if file_path:
        set_verification_marker(state_dir, "Read", file_path)


def track_web_search(tool_input: dict, state_dir) -> None:
    query = first_nonempty(tool_input, ["query", "q"])
    set_marker(state_dir, "fact_verification_attempted", f"WebSearch:{query}")
    set_marker(state_dir, "fact_verification_last_tool", "WebSearch")
    if query:
        set_marker(state_dir, "fact_verification_last_source", f"WebSearch query: {query}")


def track_web_fetch(tool_input: dict, state_dir) -> None:
    url = first_nonempty(tool_input, ["url"])
    domain = ""
    if url:
        try:
            domain = urlparse(url).netloc.lower()
        except ValueError:
            domain = ""
    set_verification_marker(state_dir, "WebFetch", url or "WebFetch", domain)


def main() -> None:
    data = get_input()
    session_id = data.get("session_id", "unknown")
    state_dir = get_state_dir(session_id)

    if not (has_marker(state_dir, "fact_verification_required") or has_marker(state_dir, "freshness_required")):
        output_allow()

    config = load_config()
    if not config.get("enabled", True):
        output_allow()

    tool_name = get_tool_name(data)
    tool_input = get_tool_input(data)

    if tool_name == "Read":
        track_read(tool_input, state_dir)
    elif tool_name == "WebSearch":
        track_web_search(tool_input, state_dir)
    elif tool_name == "WebFetch":
        track_web_fetch(tool_input, state_dir)
    elif tool_name == "Bash":
        track_bash(tool_input, state_dir)
    elif tool_name and is_trusted_mcp_tool(tool_name, config):
        set_verification_marker(state_dir, tool_name, tool_name)

    output_allow()


if __name__ == "__main__":
    main()
