"""
UserPromptSubmit hook.

Detects prompts that are likely to produce material factual assertions and
injects a verification-first instruction into Claude's working context.
"""

from __future__ import annotations

import hashlib
import json
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

USER_FACT_PATTERNS = [
    r"\bi am\b",
    r"\bi have\b",
    r"\bi had\b",
    r"\bwe are\b",
    r"\bwe have\b",
    r"\bit is\b",
    r"\bit's\b",
    r"\bit was\b",
    r"\bthere is\b",
    r"\bthere are\b",
    r"\bthere was\b",
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

ASSERTIVE_CLAIM_VERB_PATTERNS = [
    r"\bis\b",
    r"\bare\b",
    r"\bwas\b",
    r"\bwere\b",
    r"\bhas\b",
    r"\bhave\b",
    r"\bhad\b",
    r"\bcan\b",
    r"\bcannot\b",
    r"\bcan't\b",
    r"\bwill\b",
    r"\bwon't\b",
    r"\bwould\b",
    r"\bshould\b",
    r"\bmust\b",
    r"\bdid\b",
    r"\bdoes\b",
    r"\bannounced?\b",
    r"\bbuilt\b",
    r"\breleased?\b",
    r"\bclosed?\b",
    r"\bopened?\b",
    r"\bmade\b",
    r"\bcaused?\b",
    r"\btriggered?\b",
    r"\bplanned?\b",
    r"\bplans\b",
    r"\bpressured?\b",
    r"\bproved?\b",
    r"\bshowed?\b",
    r"\bcut\b",
    r"\breached?\b",
    r"\bsecured?\b",
    r"\bremoved?\b",
    r"\bneutralized?\b",
    r"\bconquer(?:s|ed)?\b",
]

COMPARATIVE_CLAIM_PATTERNS = [
    r"\blowest\b",
    r"\bhighest\b",
    r"\bmost\b",
    r"\bleast\b",
    r"\blargest\b",
    r"\bsmallest\b",
    r"\bbiggest\b",
    r"\bbest\b",
    r"\bworst\b",
    r"\bfirst\b",
    r"\blast\b",
    r"\bonly\b",
    r"\btop\b",
    r"\bleading\b",
    r"\bfastest\b",
    r"\bslowest\b",
    r"\bnewest\b",
    r"\boldest\b",
]

EXISTENCE_CLAIM_PATTERNS = [
    r"\bthere is no\b",
    r"\bthere are no\b",
    r"\bdoes not exist\b",
    r"\bdoesn't exist\b",
    r"\bdo not exist\b",
    r"\bdon't exist\b",
    r"\bno such\b",
    r"\bexists\b",
    r"\bexist\b",
]

ENTITY_HINT_PATTERN = re.compile(r"\b(?:[A-Z][a-z]+(?:[-'][A-Za-z]+)?|[A-Z]{2,}|\d{1,4})\b")
LOWERCASE_SUBJECT_CLAIM_PATTERN = re.compile(
    r"^(?:the\s+)?(?:[a-z0-9][\w&'-]*\s+){1,8}(?:is|are|was|were|has|have|had|can|cannot|can't|will|won't|would|should|must|did|does)\b",
    re.IGNORECASE,
)

FACT_MARKERS = [
    "fact_prompt_hash",
    "fact_prompt_eval.json",
    "fact_verification_required",
    "freshness_required",
    "response_shape_required",
    "response_shape_mode",
    "fact_verification_reason",
    "fact_verification_attempted",
    "fact_verification_satisfied",
    "fact_verification_last_source",
    "fact_verification_last_tool",
    "fact_verification_last_domain",
    "fact_stop_missing_assistant_message",
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


def split_sentences(text: str) -> list[str]:
    return [fragment.strip() for fragment in re.split(r"(?<=[.!?])\s+|\n+", text) if fragment.strip()]


def count_assertive_claim_sentences(text: str) -> tuple[int, list[str]]:
    count = 0
    examples: list[str] = []
    for sentence in split_sentences(text):
        if len(sentence) < 30:
            continue
        lowered = sentence.lower()
        if sentence.endswith("?"):
            continue
        if not has_any_pattern(lowered, ASSERTIVE_CLAIM_VERB_PATTERNS):
            continue
        has_claim_anchor = (
            ENTITY_HINT_PATTERN.search(sentence)
            or has_any_pattern(sentence, EXTERNAL_WORLD_PATTERNS)
            or has_any_pattern(lowered, COMPARATIVE_CLAIM_PATTERNS)
            or has_any_pattern(lowered, EXISTENCE_CLAIM_PATTERNS)
            or LOWERCASE_SUBJECT_CLAIM_PATTERN.search(sentence)
        )
        if not has_claim_anchor:
            continue
        count += 1
        if len(examples) < 3:
            examples.append(sentence[:200])
    return count, examples


def write_prompt_eval(
    state_dir,
    prompt_hash: str,
    require_verification: bool,
    freshness_required: bool,
    reason: str,
    score: int,
    threshold: int,
    claim_sentence_count: int,
    claim_examples: list[str],
    reasons: list[str],
) -> None:
    payload = {
        "prompt_hash": prompt_hash,
        "require_verification": require_verification,
        "freshness_required": freshness_required,
        "reason": reason,
        "score": score,
        "threshold": threshold,
        "claim_sentence_count": claim_sentence_count,
        "claim_examples": claim_examples,
        "reasons": reasons,
    }
    set_marker(state_dir, "fact_prompt_eval.json", json.dumps(payload, indent=2))


def choose_response_shape_mode(claim_sentence_count: int) -> str:
    return "analysis_brief" if claim_sentence_count >= 2 else "factual_brief"


def required_response_shape(shape_mode: str) -> list[str]:
    if shape_mode == "analysis_brief":
        return ["Bottom line", "Verified facts", "Analysis", "Sources"]
    return ["Bottom line", "Verified facts", "Sources"]


def build_additional_context(freshness_required: bool, claim_sentence_count: int, shape_mode: str) -> str:
    context = (
        "Verification-first mode is active for this prompt. Before presenting material facts as established, "
        "verify them from reliable sources when possible. Reliable sources include local files, trusted MCP data, "
        "and direct web fetches or searches of authoritative sources. If verification cannot be completed after a good-faith attempt, label "
        "the statement as provisional or unverified instead of presenting it as confirmed fact."
    )
    context += (
        " Do not provide substantive analysis, pushback, critique, or theory-testing before at least one verification step occurs. "
        "If you say anything before verifying, limit it to one short sentence such as: "
        "\"Interesting argument. Let me verify the facts first.\" Then immediately use tools. "
        "After verification and reasoning, give a direct, thoughtful answer with calibrated confidence. "
        "Do not turn the visible response into a self-critique, process diary, or long narration of your own failure mode unless verification genuinely failed or the sources materially conflict."
    )
    if freshness_required:
        context += " Current or time-sensitive claims deserve especially careful verification."
    if claim_sentence_count >= 1:
        context += (
            " When the user advances a substantive thesis supported by factual predicates, decompose the major claims, verify them, "
            "and engage the argument on the merits. Do not substitute a purely structural or epistemic critique for analysis of the actual claims."
        )
    required_sections = ", ".join(f"{section}:" for section in required_response_shape(shape_mode))
    context += (
        " Use this exact final-answer structure: {}. "
        "Put source links under Sources: using markdown links where possible."
    ).format(required_sections)
    return context


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
    if has_any_pattern(lowered, USER_FACT_PATTERNS):
        score += 1
        reasons.append("user-supplied factual premise")

    if has_any_pattern(lowered, COMPARATIVE_CLAIM_PATTERNS):
        score += 2
        reasons.append("comparative or superlative factual claim")

    if has_any_pattern(lowered, EXISTENCE_CLAIM_PATTERNS):
        score += 2
        reasons.append("existence or non-existence claim")

    claim_sentence_count, claim_examples = count_assertive_claim_sentences(text)
    if claim_sentence_count >= 2:
        score += 3
        reasons.append("multi-claim factual narrative")
    elif claim_sentence_count == 1:
        score += 1
        reasons.append("single assertive factual claim")

    threshold = int(config.get("prompt_score_threshold", 2))
    require_verification = score >= threshold
    freshness_required = has_any_pattern(lowered, TEMPORAL_PATTERNS)
    reason = ", ".join(dict.fromkeys(reasons)) if reasons else "material factual assertion risk"
    return require_verification, freshness_required, reason, score, threshold, claim_sentence_count, claim_examples, reasons


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

    require_verification, freshness_required, reason, score, threshold, claim_sentence_count, claim_examples, reasons = classify_prompt(prompt, config)
    write_prompt_eval(
        state_dir,
        hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        require_verification,
        freshness_required,
        reason,
        score,
        threshold,
        claim_sentence_count,
        claim_examples,
        reasons,
    )
    if not require_verification:
        return

    set_marker(state_dir, "fact_verification_required", "true")
    set_marker(state_dir, "fact_verification_reason", reason)
    if freshness_required:
        set_marker(state_dir, "freshness_required", "true")
    shape_mode = choose_response_shape_mode(claim_sentence_count)
    set_marker(state_dir, "response_shape_required", "true")
    set_marker(state_dir, "response_shape_mode", shape_mode)

    context = build_additional_context(freshness_required, claim_sentence_count, shape_mode)
    output_user_prompt_context(context)


if __name__ == "__main__":
    main()
