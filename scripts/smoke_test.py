"""
Local smoke test for the standalone hook set.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"
TEMP = Path(tempfile.gettempdir())
SESSION = "standalone-fact-hook-smoke"
STATE = TEMP / f"fact-verification-{SESSION}"
PYTHON = sys.executable

sys.path.insert(0, str(HOOKS))

from verification_stop_gate import (  # noqa: E402
    get_last_assistant_message,
    response_has_verification_caveat,
    response_is_non_assertive,
)


def run(script_name: str, payload: dict) -> dict:
    proc = subprocess.run(
        [PYTHON, str(HOOKS / script_name)],
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


def expect(name: str, result: dict, predicate, failures: list[str]) -> None:
    if not predicate(result):
        failures.append(f"{name} failed: {json.dumps(result, ensure_ascii=True)}")


def reset_state() -> None:
    if STATE.exists():
        shutil.rmtree(STATE)
    STATE.mkdir(parents=True, exist_ok=True)


def write_transcript(path: Path, rows: list[object]) -> None:
    lines = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_bool(name: str, value: bool) -> tuple[str, dict]:
    return (
        name,
        {
            "code": 0 if value else 1,
            "stdout": "",
            "stderr": "" if value else "boolean check failed",
        },
    )


def main() -> None:
    reset_state()

    transcript_dir = TEMP / f"fact-hook-transcripts-{SESSION}"
    if transcript_dir.exists():
        shutil.rmtree(transcript_dir)
    transcript_dir.mkdir(parents=True, exist_ok=True)

    results = []
    prompt_payload = {
        "session_id": SESSION,
        "prompt": "What is the latest Claude Code hook schema as of today?",
    }
    narrative_prompt_payload = {
        "session_id": SESSION,
        "prompt": (
            "I think many critics misunderstand the administration's plan. "
            "Trump built new Gulf alliances and repositioned trade pressure against China. "
            "He now plans to neutralize Iran, cut off cheap oil flows, and drive an AI race before the decade is over."
        ),
    }
    declarative_comparative_payload = {
        "session_id": SESSION,
        "prompt": "the mandalorian and gragu was the lowest grossing star wars move in history",
    }

    failures: list[str] = []
    results.append(("prompt_gate", run("fact_prompt_gate.py", prompt_payload)))
    results.append(("narrative_prompt_gate", run("fact_prompt_gate.py", narrative_prompt_payload)))
    results.append(("declarative_comparative_gate", run("fact_prompt_gate.py", declarative_comparative_payload)))

    unverified_stop = {
        "session_id": SESSION,
        "last_assistant_message": "The latest hook schema includes Stop, PreToolUse, PostToolUse, and UserPromptSubmit.",
    }
    structured_stop = {
        "session_id": SESSION,
        "last_assistant_message": (
            "Bottom line: The latest Claude Code hook schema includes Stop, PreToolUse, PostToolUse, and UserPromptSubmit.\n"
            "Verified facts:\n"
            "- The current hook schema includes those event families in the tested configuration.\n"
            "Sources:\n"
            "- [Claude Code hooks docs](https://docs.anthropic.com/en/docs/claude-code/hooks)"
        ),
    }
    results.append(("stop_blocks_unverified", run("verification_stop_gate.py", unverified_stop)))

    verified_read = {
        "session_id": SESSION,
        "tool_name": "Read",
        "tool_input": {"file_path": str(ROOT / "README.md")},
    }
    results.append(("track_read", run("track_verification.py", verified_read)))
    results.append(("stop_blocks_unstructured_after_verification", run("verification_stop_gate.py", unverified_stop)))
    results.append(("stop_allows_structured_verified", run("verification_stop_gate.py", structured_stop)))

    reset_state()
    run("fact_prompt_gate.py", prompt_payload)
    caveated_stop = {
        "session_id": SESSION,
        "last_assistant_message": "I have not independently verified this, so treat this as a provisional answer based on currently available information.",
    }
    results.append(("stop_blocks_caveat_without_attempt", run("verification_stop_gate.py", caveated_stop)))

    reset_state()
    run("fact_prompt_gate.py", prompt_payload)
    searched = {
        "session_id": SESSION,
        "tool_name": "WebSearch",
        "tool_input": {"query": "latest Claude Code hook schema"},
    }
    results.append(("track_web_search", run("track_verification.py", searched)))
    results.append(("stop_allows_websearch_verified", run("verification_stop_gate.py", structured_stop)))

    reset_state()
    run("fact_prompt_gate.py", narrative_prompt_payload)
    missing_message_stop = {
        "session_id": SESSION,
        "stop_hook_active": False,
    }
    results.append(("stop_blocks_missing_message", run("verification_stop_gate.py", missing_message_stop)))

    reset_state()
    run("fact_prompt_gate.py", prompt_payload)
    clarifying_stop = {
        "session_id": SESSION,
        "last_assistant_message": "Could you clarify which Claude Code host version and date range you want checked?",
    }
    results.append(("stop_allows_clarifying_question", run("verification_stop_gate.py", clarifying_stop)))

    nested_transcript = transcript_dir / "nested-assistant.jsonl"
    nested_transcript_message = "The latest hook schema includes Stop, PreToolUse, PostToolUse, and UserPromptSubmit."
    write_transcript(
        nested_transcript,
        [
            "",
            "not-json",
            {"role": "user", "content": "What is the latest Claude Code hook schema?"},
            {
                "type": "assistant_message",
                "message": {
                    "content": [
                        {"type": "thinking", "text": "I should verify this."},
                        {"type": "text", "text": nested_transcript_message},
                    ]
                },
            },
        ],
    )
    results.append(
        check_bool(
            "extracts_nested_transcript_assistant_message",
            get_last_assistant_message({"transcript_path": str(nested_transcript)}) == nested_transcript_message,
        )
    )

    reset_state()
    run("fact_prompt_gate.py", prompt_payload)
    results.append(
        (
            "stop_blocks_nested_transcript_assistant",
            run(
                "verification_stop_gate.py",
                {"session_id": SESSION, "transcript_path": str(nested_transcript)},
            ),
        )
    )

    malformed_transcript = transcript_dir / "malformed-only.jsonl"
    write_transcript(
        malformed_transcript,
        [
            "",
            "{not json",
            {"role": "user", "content": "What is the latest Claude Code hook schema?"},
            {"type": "assistant_message", "message": {"content": []}},
        ],
    )
    reset_state()
    run("fact_prompt_gate.py", prompt_payload)
    results.append(
        (
            "stop_allows_malformed_transcript_when_active",
            run(
                "verification_stop_gate.py",
                {
                    "session_id": SESSION,
                    "transcript_path": str(malformed_transcript),
                    "stop_hook_active": True,
                },
            ),
        )
    )

    results.extend(
        [
            check_bool(
                "detects_unable_to_verify_caveat",
                response_has_verification_caveat("I was unable to verify this from reliable sources."),
            ),
            check_bool(
                "detects_best_effort_caveat",
                response_has_verification_caveat("This is a best-effort answer based on currently available information."),
            ),
            check_bool(
                "does_not_treat_plain_answer_as_caveat",
                not response_has_verification_caveat("This answer is verified and final."),
            ),
            check_bool(
                "detects_non_assertive_clarifying_question",
                response_is_non_assertive("Could you clarify which release channel you mean?"),
            ),
        ]
    )

    py_compile = subprocess.run(
        [
            PYTHON,
            "-m",
            "py_compile",
            str(HOOKS / "common.py"),
            str(HOOKS / "fact_prompt_gate.py"),
            str(HOOKS / "track_verification.py"),
            str(HOOKS / "verification_stop_gate.py"),
            str(ROOT / "scripts" / "smoke_test.py"),
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

    result_map = dict(results)
    expect("prompt_gate", result_map["prompt_gate"], lambda item: bool(item["stdout"]), failures)
    expect("narrative_prompt_gate", result_map["narrative_prompt_gate"], lambda item: bool(item["stdout"]), failures)
    expect("declarative_comparative_gate", result_map["declarative_comparative_gate"], lambda item: bool(item["stdout"]), failures)
    expect("stop_blocks_unverified", result_map["stop_blocks_unverified"], lambda item: "\"decision\": \"block\"" in item["stdout"], failures)
    expect("track_read", result_map["track_read"], lambda item: item["code"] == 0, failures)
    expect("stop_blocks_unstructured_after_verification", result_map["stop_blocks_unstructured_after_verification"], lambda item: "\"decision\": \"block\"" in item["stdout"], failures)
    expect("stop_allows_structured_verified", result_map["stop_allows_structured_verified"], lambda item: item["code"] == 0 and not item["stdout"], failures)
    expect("stop_blocks_caveat_without_attempt", result_map["stop_blocks_caveat_without_attempt"], lambda item: "\"decision\": \"block\"" in item["stdout"], failures)
    expect("track_web_search", result_map["track_web_search"], lambda item: item["code"] == 0, failures)
    expect("stop_allows_websearch_verified", result_map["stop_allows_websearch_verified"], lambda item: item["code"] == 0 and not item["stdout"], failures)
    expect("stop_blocks_missing_message", result_map["stop_blocks_missing_message"], lambda item: "\"decision\": \"block\"" in item["stdout"], failures)
    expect("stop_allows_clarifying_question", result_map["stop_allows_clarifying_question"], lambda item: item["code"] == 0 and not item["stdout"], failures)
    expect("extracts_nested_transcript_assistant_message", result_map["extracts_nested_transcript_assistant_message"], lambda item: item["code"] == 0, failures)
    expect("stop_blocks_nested_transcript_assistant", result_map["stop_blocks_nested_transcript_assistant"], lambda item: "\"decision\": \"block\"" in item["stdout"], failures)
    expect("stop_allows_malformed_transcript_when_active", result_map["stop_allows_malformed_transcript_when_active"], lambda item: item["code"] == 0 and not item["stdout"], failures)
    expect("detects_unable_to_verify_caveat", result_map["detects_unable_to_verify_caveat"], lambda item: item["code"] == 0, failures)
    expect("detects_best_effort_caveat", result_map["detects_best_effort_caveat"], lambda item: item["code"] == 0, failures)
    expect("does_not_treat_plain_answer_as_caveat", result_map["does_not_treat_plain_answer_as_caveat"], lambda item: item["code"] == 0, failures)
    expect("detects_non_assertive_clarifying_question", result_map["detects_non_assertive_clarifying_question"], lambda item: item["code"] == 0, failures)
    expect("py_compile", result_map["py_compile"], lambda item: item["code"] == 0, failures)

    print(json.dumps(results, indent=2))
    shutil.rmtree(transcript_dir, ignore_errors=True)
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
