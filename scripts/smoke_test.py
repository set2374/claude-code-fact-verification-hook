"""
Local smoke test for the standalone hook set.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
TEMP = Path(tempfile.gettempdir())
SESSION = "standalone-fact-hook-smoke"
STATE = TEMP / f"fact-verification-{SESSION}"


def run(script_name: str, payload: dict) -> dict:
    proc = subprocess.run(
        ["python", str(HOOKS / script_name)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )
    return {
        "code": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def main() -> None:
    if STATE.exists():
        shutil.rmtree(STATE)
    STATE.mkdir(parents=True, exist_ok=True)

    results = []
    prompt_payload = {
        "session_id": SESSION,
        "prompt": "What is the latest Claude Code hook schema as of today?",
    }

    results.append(("prompt_gate", run("fact_prompt_gate.py", prompt_payload)))

    unverified_stop = {
        "session_id": SESSION,
        "last_assistant_message": "The latest hook schema includes Stop, PreToolUse, PostToolUse, and UserPromptSubmit.",
    }
    results.append(("stop_blocks_unverified", run("verification_stop_gate.py", unverified_stop)))

    verified_read = {
        "session_id": SESSION,
        "tool_name": "Read",
        "tool_input": {"file_path": str(ROOT / "README.md")},
    }
    results.append(("track_read", run("track_verification.py", verified_read)))
    results.append(("stop_allows_verified", run("verification_stop_gate.py", unverified_stop)))

    if STATE.exists():
        shutil.rmtree(STATE)
    STATE.mkdir(parents=True, exist_ok=True)
    run("fact_prompt_gate.py", prompt_payload)
    caveated_stop = {
        "session_id": SESSION,
        "last_assistant_message": "I have not independently verified this, so treat this as a provisional answer based on currently available information.",
    }
    results.append(("stop_allows_caveat", run("verification_stop_gate.py", caveated_stop)))

    py_compile = subprocess.run(
        [
            "python",
            "-m",
            "py_compile",
            str(HOOKS / "common.py"),
            str(HOOKS / "fact_prompt_gate.py"),
            str(HOOKS / "track_verification.py"),
            str(HOOKS / "verification_stop_gate.py"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    results.append(
        (
            "py_compile",
            {
                "code": py_compile.returncode,
                "stdout": py_compile.stdout.strip(),
                "stderr": py_compile.stderr.strip(),
            },
        )
    )

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
