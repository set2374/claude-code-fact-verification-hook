"""
Local smoke test for the standalone hook set.

Includes expanded tests for transcript payload variants as requested in #2.
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


def expect(name: str, result: dict, predicate, failures: list[str]) -> None:
    if not predicate(result):
        failures.append(f"{name} failed: {json.dumps(result, ensure_ascii=True)}")


def fresh_session(session_id: str) -> None:
    """Reset state for a fresh session."""
    state = TEMP / f"fact-verification-{session_id}"
    if state.exists():
        shutil.rmtree(state)
    state.mkdir(parents=True, exist_ok=True)


def run_gate(session_id: str, prompt: str) -> dict:
    """Run fact_prompt_gate for a session."""
    return run("fact_prompt_gate.py", {"session_id": session_id, "prompt": prompt})


def run_track(session_id: str, tool_name: str, tool_input: dict) -> dict:
    """Run track_verification for a session."""
    return run("track_verification.py", {
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
    })


def run_stop(session_id: str, msg: str, **extra) -> dict:
    """Run verification_stop_gate for a session."""
    payload = {"session_id": session_id, "last_assistant_message": msg}
    payload.update(extra)
    return run("verification_stop_gate.py", payload)


def write_transcript(path: Path, lines: list[dict]) -> None:
    """Write a JSONL transcript file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")


def main() -> None:
    fresh_session(SESSION)

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

    fresh_session(SESSION)
    run("fact_prompt_gate.py", prompt_payload)
    caveated_stop = {
        "session_id": SESSION,
        "last_assistant_message": "I have not independently verified this, so treat this as a provisional answer based on currently available information.",
    }
    results.append(("stop_blocks_caveat_without_attempt", run("verification_stop_gate.py", caveated_stop)))

    fresh_session(SESSION)
    run("fact_prompt_gate.py", prompt_payload)
    searched = {
        "session_id": SESSION,
        "tool_name": "WebSearch",
        "tool_input": {"query": "latest Claude Code hook schema"},
    }
    results.append(("track_web_search", run("track_verification.py", searched)))
    results.append(("stop_allows_websearch_verified", run("verification_stop_gate.py", structured_stop)))

    fresh_session(SESSION)
    run("fact_prompt_gate.py", narrative_prompt_payload)
    missing_message_stop = {
        "session_id": SESSION,
        "stop_hook_active": False,
    }
    results.append(("stop_blocks_missing_message", run("verification_stop_gate.py", missing_message_stop)))

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

    # ================================================================
    # Expanded tests: transcript payload variants (#2)
    # ================================================================

    S2 = f"{SESSION}-transcript"

    # Test: transcript with assistant content in nested "message" dict
    fresh_session(S2)
    run_gate(S2, "What is the current price of Bitcoin today?")
    run_track(S2, "WebSearch", {"query": "bitcoin price"})
    transcript_path = TEMP / f"fact-verification-{S2}" / "transcript.jsonl"
    write_transcript(transcript_path, [
        {"role": "user", "content": "What is the current price of Bitcoin today?"},
        {"role": "assistant", "content": {"type": "text", "text": "Let me check that for you."}},
        {"role": "assistant", "content": [
            {"type": "text", "text": "Bottom line: BTC is around $67,000.\nVerified facts:\n- Coingecko reports ~$67K\nSources:\n- [CoinGecko](https://coingecko.com)"}
        ]},
    ])
    transcript_stop = {
        "session_id": S2,
        "transcript_path": str(transcript_path),
    }
    results.append(("transcript_nested_content_list", run("verification_stop_gate.py", transcript_stop)))

    # Test: clarifying question detection via transcript
    fresh_session(S2)
    run_gate(S2, "What is the latest Node.js LTS version as of today?")
    transcript_path2 = TEMP / f"fact-verification-{S2}" / "transcript2.jsonl"
    write_transcript(transcript_path2, [
        {"role": "user", "content": "What is the latest Node.js LTS version as of today?"},
        {"role": "assistant", "content": "Could you clarify whether you mean the Active LTS or the Maintenance LTS version?"},
    ])
    transcript_clarifying = {
        "session_id": S2,
        "transcript_path": str(transcript_path2),
    }
    results.append(("transcript_clarifying_question", run("verification_stop_gate.py", transcript_clarifying)))

    # Test: caveat detection edge case - "best-effort" wording
    fresh_session(S2)
    run_gate(S2, "What are the current top 10 movies on Netflix?")
    transcript_path3 = TEMP / f"fact-verification-{S2}" / "transcript3.jsonl"
    write_transcript(transcript_path3, [
        {"role": "user", "content": "What are the current top 10 movies on Netflix?"},
        {"role": "assistant", "content": "This is a best-effort answer and may not reflect the current moment."},
    ])
    transcript_caveat = {
        "session_id": S2,
        "transcript_path": str(transcript_path3),
    }
    results.append(("transcript_best_effort_caveat", run("verification_stop_gate.py", transcript_caveat)))

    # Test: empty transcript lines should fail open, not crash
    fresh_session(S2)
    run_gate(S2, "Who won the last Super Bowl?")
    transcript_path4 = TEMP / f"fact-verification-{S2}" / "transcript4.jsonl"
    write_transcript(transcript_path4, [
        "",
        "not json",
        "",
    ])
    transcript_empty = {
        "session_id": S2,
        "transcript_path": str(transcript_path4),
    }
    results.append(("transcript_empty_malformed_lines", run("verification_stop_gate.py", transcript_empty)))

    # Test: transcript with assistant content nested under "message" key
    fresh_session(S2)
    run_gate(S2, "What is the latest Python version as of today?")
    run_track(S2, "WebSearch", {"query": "latest python version"})
    transcript_path5 = TEMP / f"fact-verification-{S2}" / "transcript5.jsonl"
    write_transcript(transcript_path5, [
        {"role": "user", "message": {"content": "What is the latest Python version as of today?"}},
        {"role": "assistant", "message": {"content": "Bottom line: Python 3.13 is the latest.\nVerified facts:\n- python.org shows 3.13\nSources:\n- [Python.org](https://python.org)"}},
    ])
    transcript_msg_nested = {
        "session_id": S2,
        "transcript_path": str(transcript_path5),
    }
    results.append(("transcript_message_nested", run("verification_stop_gate.py", transcript_msg_nested)))

    # Test: "unable to verify" caveat via transcript
    fresh_session(S2)
    run_gate(S2, "What is the GDP of Tuvalu in 2026?")
    transcript_path6 = TEMP / f"fact-verification-{S2}" / "transcript6.jsonl"
    write_transcript(transcript_path6, [
        {"role": "user", "content": "What is the GDP of Tuvalu in 2026?"},
        {"role": "assistant", "content": "I was unable to verify this figure from authoritative sources. Treat as provisional."},
    ])
    transcript_unable = {
        "session_id": S2,
        "transcript_path": str(transcript_path6),
    }
    results.append(("transcript_unable_to_verify", run("verification_stop_gate.py", transcript_unable)))

    # Test: transcript with only user messages (no assistant message)
    fresh_session(S2)
    run_gate(S2, "What is the current population of Tokyo?")
    transcript_path7 = TEMP / f"fact-verification-{S2}" / "transcript7.jsonl"
    write_transcript(transcript_path7, [
        {"role": "user", "content": "What is the current population of Tokyo?"},
    ])
    transcript_no_assistant = {
        "session_id": S2,
        "transcript_path": str(transcript_path7),
    }
    results.append(("transcript_no_assistant_message", run("verification_stop_gate.py", transcript_no_assistant)))

    # Test: transcript path that does not exist
    fresh_session(S2)
    run_gate(S2, "What is the current price of Ethereum?")
    transcript_missing = {
        "session_id": S2,
        "transcript_path": "/nonexistent/path/transcript.jsonl",
    }
    results.append(("transcript_missing_file", run("verification_stop_gate.py", transcript_missing)))

    # Cleanup
    for sid in [SESSION, S2]:
        state = TEMP / f"fact-verification-{sid}"
        if state.exists():
            shutil.rmtree(state)

    # ================================================================
    # Assertions
    # ================================================================

    result_map = dict(results)
    expect("prompt_gate", result_map["prompt_gate"], lambda item: bool(item["stdout"]), failures)
    expect("narrative_prompt_gate", result_map["narrative_prompt_gate"], lambda item: bool(item["stdout"]), failures)
    expect("declarative_comparative_gate", result_map["declarative_comparative_gate"], lambda item: bool(item["stdout"]), failures)
    expect("stop_blocks_unverified", result_map["stop_blocks_unverified"], lambda item: '"decision": "block"' in item["stdout"], failures)
    expect("track_read", result_map["track_read"], lambda item: item["code"] == 0, failures)
    expect("stop_blocks_unstructured_after_verification", result_map["stop_blocks_unstructured_after_verification"], lambda item: '"decision": "block"' in item["stdout"], failures)
    expect("stop_allows_structured_verified", result_map["stop_allows_structured_verified"], lambda item: item["code"] == 0 and not item["stdout"], failures)
    expect("stop_blocks_caveat_without_attempt", result_map["stop_blocks_caveat_without_attempt"], lambda item: '"decision": "block"' in item["stdout"], failures)
    expect("track_web_search", result_map["track_web_search"], lambda item: item["code"] == 0, failures)
    expect("stop_allows_websearch_verified", result_map["stop_allows_websearch_verified"], lambda item: item["code"] == 0 and not item["stdout"], failures)
    expect("stop_blocks_missing_message", result_map["stop_blocks_missing_message"], lambda item: '"decision": "block"' in item["stdout"], failures)
    expect("py_compile", result_map["py_compile"], lambda item: item["code"] == 0, failures)

    # Transcript variant assertions
    expect("transcript_nested_content_list", result_map["transcript_nested_content_list"], lambda item: item["code"] == 0, failures)
    expect("transcript_clarifying_question", result_map["transcript_clarifying_question"], lambda item: item["code"] == 0, failures)
    expect("transcript_best_effort_caveat", result_map["transcript_best_effort_caveat"], lambda item: item["code"] == 0, failures)
    expect("transcript_empty_malformed_lines", result_map["transcript_empty_malformed_lines"], lambda item: item["code"] == 0, failures)
    expect("transcript_message_nested", result_map["transcript_message_nested"], lambda item: item["code"] == 0, failures)
    expect("transcript_unable_to_verify", result_map["transcript_unable_to_verify"], lambda item: item["code"] == 0, failures)
    expect("transcript_no_assistant_message", result_map["transcript_no_assistant_message"], lambda item: '"decision": "block"' in item["stdout"], failures)
    expect("transcript_missing_file", result_map["transcript_missing_file"], lambda item: '"decision": "block"' in item["stdout"], failures)

    print(json.dumps(results, indent=2))
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()