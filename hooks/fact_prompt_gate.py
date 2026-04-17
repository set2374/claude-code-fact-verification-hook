"""
UserPromptSubmit hook.

Detects prompts that are likely to produce material factual assertions and
injects a verification-first instruction into Claude's working context.
"""

from __future__ import annotations

import hashlib
import re

from common import (
    clear_marker,
    get_input,
    get_state_dir,
    load_config,
    output_user_prompt_context,
    set_marker,
)


TEMPORAL_PATTERNS = [
    r"\bas of\b",
    r"\bcurrent\b",
    r"\blatest\b",
    r"\bmost recent\b",
    r"\brecent\b",
    r"\btoday\b",
    r"\byesterday\b",
    r"\bthis week\b",
    r"\bthis month\b",
    r"\bthis year\b",
    r"\bupdated?\b",
    r"\brelease(?:d)?\b",
    r"\bannounced?\b",
    r"\bversion\b",
    r"\bprice\b",
    r"\bpricing\b",
]

VERIFY_PATTERNS = [
    r"\bverify\b",
    r"\bcheck\b",
    r"\bconfirm\b",
    r"\blook up\b",
    r"\bsearch\b",
    r"\bbrowse\b",
    r"\bweb ?search\b",
    r"\btrue or false\b",
]

FACTUAL_REQUEST_PATTERNS = [
    r"\bwhat(?:'s| is| are| was| were)\b",
    r"\bwho(?:'s| is| was)\b",
    r"\bwhen(?: did| is| was)\b",
    r"\bwhere(?: is| was)\b",
    r"\bhow many\b",
    r"\bdoes\b",
    r"\bdid\b",
    r"\bcan you tell me\b",
    r"\bstatus of\b",
]

EXTERNAL_WORLD_PATTERNS = [
    r"https?://",
    r"\b(api|sdk|library|package|framework|plugin|mcp|model|pricing|policy|law|rule|regulation|deadline|ceo|president|judge|company|product)\b",
    r"\b\d{4}-\d{2}-\d{2}\b",
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b",
    r"\bv?\d+\.\d+(?:\.\d+)?\b",
]

NON_FACTUAL_PATTERNS = [
    r"\btranslate\b",
    r"\brewrite\b",
    r"\bparaphrase\b",
    r"\bproofread\b",
    r"\bcreative\b",
    r"\bstory\b",
    r"\bpoem\b",
]

CODE_ACTION_PATTERNS = [
    r"\bwrite\b",
    r"\bpatch\b",
    r"\brefactor\b",
    r"\bfix\b",
    r"\bimplement\b",
    r"\binstall\b",
    r"\bdeploy\b",
    r"\bcommit\b",
    r"\bpush\b",
]

FACT_MARKERS = [
    "fact_prompt_hash",
    "fact_verification_required",
    "freshness_required",
    "fact_verification_reason",
    "fact_verification_attempted",
    "fact_verification_satisfied",
    "fact_verification_last_source",
    "fact_verification_last_tool",
    "fact_verification_last_domain",
    "skip_fact_verification",
]


def first_nonempty(data: dict, keys: list[str]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_prompt(data: dict) -> str:
    prompt = first_nonempty(data, ["prompt", "user_prompt", "message", "text", "input_text"])
    if prompt:
        return prompt

    payload = data.get("payload")
    if isinstance(payload, dict):
        prompt = first_nonempty(payload, ["prompt", "user_prompt", "message", "text", "input_text"])
        if prompt:
            return prompt

    messages = data.get("messages")
    if isinstance(messages, list):
        for message in reversed(messages):
            if not isinstance(message, dict):
                continue
            if str(message.get("role", "")).lower() != "user":
                continue
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, str):
                        parts.append(item.strip())
                    elif isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str) and text.strip():
                            parts.append(text.strip())
                if parts:
                    return "\n".join(parts)
    return ""


def has_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)


def classify_prompt(prompt: str, config: dict) -> tuple[bool, bool, str]:
    text = prompt.strip()
    lowered = text.lower()
    reasons: list[str] = []
    score = 0

    if not config.get("enabled", True):
        return False, False, "disabled"
    if not text:
        return False, False, "empty prompt"

    if has_any_pattern(lowered, NON_FACTUAL_PATTERNS) and not (
        has_any_pattern(lowered, TEMPORAL_PATTERNS) or has_any_pattern(lowered, VERIFY_PATTERNS)
    ):
        return False, False, "non-factual writing task"

    if has_any_pattern(lowered, CODE_ACTION_PATTERNS) and not (
        has_any_pattern(lowered, TEMPORAL_PATTERNS)
        or has_any_pattern(lowered, VERIFY_PATTERNS)
        or has_any_pattern(lowered, FACTUAL_REQUEST_PATTERNS)
    ):
        return False, False, "implementation task without external fact risk"

    if has_any_pattern(lowered, TEMPORAL_PATTERNS):
        score += 3
        reasons.append("time-sensitive/current facts")
    if has_any_pattern(lowered, VERIFY_PATTERNS):
        score += 3
        reasons.append("explicit verification request")
    if has_any_pattern(lowered, FACTUAL_REQUEST_PATTERNS):
        score += 2
        reasons.append("factual question")
    if has_any_pattern(text, EXTERNAL_WORLD_PATTERNS):
        score += 1
        reasons.append("external-world entity or version/date cue")

    threshold = int(config.get("prompt_score_threshold", 2))
    require_verification = score >= threshold
    freshness_required = has_any_pattern(lowered, TEMPORAL_PATTERNS)
    reason = ", ".join(dict.fromkeys(reasons)) if reasons else "material factual assertion risk"
    return require_verification, freshness_required, reason


def main() -> None:
    data = get_input()
    session_id = data.get("session_id", "unknown")
    state_dir = get_state_dir(session_id)
    config = load_config()

    for marker in FACT_MARKERS:
        clear_marker(state_dir, marker)

    prompt = extract_prompt(data)
    if not prompt:
        return

    set_marker(state_dir, "fact_prompt_hash", hashlib.sha256(prompt.encode("utf-8")).hexdigest())

    require_verification, freshness_required, reason = classify_prompt(prompt, config)
    if not require_verification:
        return

    set_marker(state_dir, "fact_verification_required", "true")
    set_marker(state_dir, "fact_verification_reason", reason)
    if freshness_required:
        set_marker(state_dir, "freshness_required", "true")

    context = (
        "Verification-first mode is active for this prompt. Before presenting material facts as established, "
        "verify them from reliable sources when possible. Reliable sources include local files, trusted MCP data, "
        "and direct web fetches or searches of authoritative sources. If verification cannot be completed, label "
        "the statement as provisional or unverified instead of presenting it as confirmed fact."
    )
    if freshness_required:
        context += " Current or time-sensitive claims deserve especially careful verification."
    output_user_prompt_context(context)


if __name__ == "__main__":
    main()
