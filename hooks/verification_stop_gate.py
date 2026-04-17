"""
Stop hook.

Blocks the turn from ending when verification-first mode is active and Claude
is about to make unsupported factual assertions without either:

1. real verification evidence, or
2. a clear caveat that the answer is provisional or unverified.
"""

from __future__ import annotations

import json
import os
import re

from common import (
    get_input,
    get_state_dir,
    has_marker,
    load_config,
    output_allow,
    output_block_stop,
    read_marker,
    set_marker,
)


FACT_CAVEAT_PATTERNS = [
    r"\bnot independently verified\b",
    r"\bcould not verify\b",
    r"\bcouldn't verify\b",
    r"\bunable to verify\b",
    r"\bnot verified\b",
    r"\bunverified\b",
    r"\bprovisional\b",
    r"\bbest[- ]effort\b",
    r"\bbased on currently available information\b",
    r"\bbased on the information provided\b",
]

NON_ASSERTIVE_PATTERNS = [
    r"^\s*(can|could|would|will)\s+you\b",
    r"^\s*(what|which|when|where|who|how)\b",
    r"\bplease (share|provide|clarify|confirm|tell me)\b",
    r"\bi need (?:more|additional|a bit more)\b",
    r"\bbefore i (?:answer|respond)\b",
    r"\bto verify this,? i need\b",
]


def first_nonempty(data: dict, keys: list[str]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [extract_text(item) for item in value]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        for key in ("text", "message", "content", "value", "output", "result"):
            if key in value:
                text = extract_text(value.get(key))
                if text:
                    return text
    return ""


def extract_assistant_text_from_obj(obj: dict) -> str:
    direct = first_nonempty(obj, ["last_assistant_message"])
    if direct:
        return direct

    role = str(obj.get("role") or obj.get("speaker") or obj.get("actor") or "").lower()
    kind = str(obj.get("type") or obj.get("event_type") or "").lower()
    is_assistant = role == "assistant" or "assistant" in kind or "claude" in role

    if is_assistant:
        for key in ("content", "message", "data", "payload"):
            text = extract_text(obj.get(key))
            if text:
                return text

    nested = obj.get("message")
    if isinstance(nested, dict):
        return extract_assistant_text_from_obj(nested)
    return ""


def load_last_assistant_message_from_transcript(data: dict) -> str:
    transcript_path = first_nonempty(data, ["transcript_path"])
    if not transcript_path or not os.path.exists(transcript_path):
        return ""

    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
    except OSError:
        return ""

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        text = extract_assistant_text_from_obj(payload)
        if text:
            return text
    return ""


def get_last_assistant_message(data: dict) -> str:
    message = first_nonempty(data, ["last_assistant_message"])
    if message:
        return message

    payload = data.get("payload")
    if isinstance(payload, dict):
        nested = first_nonempty(payload, ["last_assistant_message"])
        if nested:
            return nested

    return load_last_assistant_message_from_transcript(data)


def response_is_non_assertive(text: str) -> bool:
    if not text.strip():
        return False
    stripped = text.strip()
    if "?" not in stripped:
        return False
    if len(stripped) > 500:
        return False
    return any(re.search(pattern, stripped, re.IGNORECASE) for pattern in NON_ASSERTIVE_PATTERNS)


def response_has_verification_caveat(text: str) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in FACT_CAVEAT_PATTERNS)


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def main() -> None:
    data = get_input()
    session_id = data.get("session_id", "unknown")
    state_dir = get_state_dir(session_id)
    config = load_config()

    if has_marker(state_dir, "skip_fact_verification"):
        output_allow()
    if not config.get("enabled", True):
        output_allow()
    if not (has_marker(state_dir, "fact_verification_required") or has_marker(state_dir, "freshness_required")):
        output_allow()
    if has_marker(state_dir, "fact_verification_satisfied"):
        output_allow()

    assistant_text = get_last_assistant_message(data)
    if not assistant_text.strip():
        set_marker(state_dir, "fact_stop_missing_assistant_message", "true")
        if truthy(data.get("stop_hook_active")):
            output_allow()
        output_block_stop(
            "[FACTUAL VERIFICATION GATE]\n"
            "Verification-first mode is active, but the Stop hook could not inspect Claude's final message.\n"
            "Per Anthropic's current hook schema, Stop should include last_assistant_message.\n"
            "Before ending the turn, restate the response with explicit verification status or verify the material facts first.\n"
        )
    if response_is_non_assertive(assistant_text):
        output_allow()
    if response_has_verification_caveat(assistant_text):
        output_allow()

    reason = read_marker(state_dir, "fact_verification_reason") or "material factual assertion risk"
    freshness_note = (
        "Current or time-sensitive claims were detected for this prompt.\n"
        if has_marker(state_dir, "freshness_required")
        else ""
    )
    last_attempt = read_marker(state_dir, "fact_verification_last_source")
    attempt_note = f"Latest verification signal: {last_attempt}\n" if last_attempt else ""

    output_block_stop(
        "[FACTUAL VERIFICATION GATE]\n"
        f"Verification-first mode is active for this prompt because of: {reason}\n"
        f"{freshness_note}"
        f"{attempt_note}"
        "Before ending the turn, do one of the following:\n"
        "  1. Verify the material facts from reliable sources such as local files, trusted MCP data, or authoritative web sources\n"
        "  2. Revise the response so any unverified factual statements are explicitly labeled as provisional or unverified\n"
        "  3. If the user wants a best-effort answer without verification, say that plainly in the response itself\n"
    )


if __name__ == "__main__":
    main()
