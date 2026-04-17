"""
Shared helpers for Claude Code factual-verification hooks.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


DEFAULT_CONFIG = {
    "enabled": True,
    "prompt_score_threshold": 2,
    "trusted_mcp_patterns": [
        r"^mcp__.*courtlistener.*",
        r"^mcp__.*github.*",
        r"^mcp__.*google.*workspace.*",
        r"^mcp__.*google.*drive.*",
        r"^mcp__.*google.*calendar.*",
        r"^mcp__.*ms365.*",
        r"^mcp__.*outlook.*",
        r"^mcp__.*notion.*",
        r"^mcp__.*linear.*",
        r"^mcp__.*slack.*",
    ],
}


def get_input() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return {}


def state_root() -> Path:
    override = os.environ.get("FACT_VERIFICATION_STATE_ROOT", "").strip()
    if override:
        return Path(override)
    return Path(tempfile.gettempdir())


def get_state_dir(session_id: str) -> Path:
    path = state_root() / f"fact-verification-{session_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def marker_path(state_dir: Path, marker: str) -> Path:
    return state_dir / marker


def has_marker(state_dir: Path, marker: str) -> bool:
    return marker_path(state_dir, marker).exists()


def set_marker(state_dir: Path, marker: str, content: str = "") -> None:
    path = marker_path(state_dir, marker)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def read_marker(state_dir: Path, marker: str) -> str:
    path = marker_path(state_dir, marker)
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def clear_marker(state_dir: Path, marker: str) -> None:
    path = marker_path(state_dir, marker)
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    path = os.environ.get("FACT_VERIFICATION_CONFIG_PATH", "").strip()
    if not path:
        return config
    file_path = Path(path)
    if not file_path.exists():
        return config
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        return config
    if isinstance(payload, dict):
        config.update(payload)
    return config


def output_allow() -> None:
    sys.exit(0)


def output_block_stop(reason: str) -> None:
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(0)


def output_user_prompt_context(context: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }
        )
    )
    sys.exit(0)
