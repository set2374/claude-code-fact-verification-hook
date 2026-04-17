# Claude Code Fact Verification Hook

A standalone Claude Code hook set that pushes the model toward: verify first, assert second.

## Why this exists

A real-world failure mode is showing up more often in Claude Code workflows:

- the model believes it already knows the answer
- it answers from training knowledge
- it only reaches for search or web tools when its uncertainty is high
- the answer can be confident, current-sounding, and wrong

That is especially risky for:

- current events
- model/version/platform questions
- laws, policies, and pricing
- anything the user explicitly asked you to verify

This project adds a lightweight forcing function using Claude Code's native hooks:

1. `UserPromptSubmit` classifies prompts that are likely to require factual verification.
2. `PostToolUse` records when Claude actually performed a meaningful verification step.
3. `Stop` blocks the turn from ending if Claude is about to make unsupported factual assertions without either verification evidence or an explicit caveat.

## Design goals

- standalone
- no private framework dependencies
- positive instruction style
- minimal moving parts
- easy to fork and tune

## Why positive instructions

The hook set is intentionally framed as:

- verify material facts from reliable sources when possible
- if you cannot verify them, say so plainly

Instead of loading the prompt with broad negative phrasing, the hooks try to create a narrow behavioral path:

- verified answer, or
- explicitly provisional answer

## How it works

### 1. Prompt gate

`hooks/fact_prompt_gate.py`

This hook looks for signals like:

- `latest`
- `current`
- `today`
- `as of`
- explicit requests like `verify`, `check`, `confirm`
- factual question patterns like `what is`, `who is`, `status of`

When the score crosses a threshold, the hook:

- marks the session as verification-sensitive
- notes whether freshness matters
- injects extra context into Claude's working context

### 2. Verification tracker

`hooks/track_verification.py`

This hook records evidence from:

- `Read`
- `WebFetch`
- `WebSearch` as an attempt signal
- `Bash` commands that look like reads or web fetches
- trusted MCP tool names matched by regex

### 3. Stop gate

`hooks/verification_stop_gate.py`

This hook allows the turn to end if:

- verification evidence exists, or
- the response clearly says it is provisional or unverified, or
- Claude is just asking a clarifying question

It blocks the turn if:

- verification-sensitive mode is active, and
- no meaningful verification evidence exists, and
- the response reads like a factual answer rather than a caveated answer

## Install

### 1. Clone the repo

```bash
git clone https://github.com/<your-username>/claude-code-fact-verification-hook.git
```

### 2. Copy the hooks somewhere stable

This repo assumes you will reference the hook scripts by absolute path from your Claude Code settings.

### 3. Optional: create a config file

Copy:

- `config.example.json`

Then set:

- `FACT_VERIFICATION_CONFIG_PATH`

if you want custom thresholds or MCP regex patterns.

### 4. Register the hooks

Use `settings.example.json` as a starting point and replace `<REPO_PATH>` with your real absolute path.

### 5. Restart Claude Code

Hook registration changes are safest after a restart or a fresh session.

## Quick smoke test

```bash
python scripts/smoke_test.py
```

The smoke test checks that:

- verification mode activates for a current/factual prompt
- an unsupported factual answer gets blocked
- a `Read` action satisfies the gate
- a clearly provisional answer is allowed

## Recommended tuning

### Lower false positives

- raise `prompt_score_threshold`
- shrink your trusted MCP regex list

### Lower false negatives

- expand temporal and factual question patterns
- add trusted MCPs that represent authoritative data in your environment

## Limitations

- This does not prove the source itself is correct. It proves Claude actually checked something.
- `WebSearch` is treated as an attempt signal, not full verification, because search alone is often too weak.
- The prompt classifier is heuristic, not semantic.
- Some hosts and toolchains may package hook payloads a little differently, so transcript fallback remains useful.

## Community goals

This repo is meant to be a contributor-friendly entry point before larger governed frameworks ship. Useful PRs would include:

- better classifiers
- better MCP trust defaults
- more tests
- platform-specific install guides
- more precise caveat detection

## References

- Anthropic Claude Code hooks docs: https://docs.anthropic.com/en/docs/claude-code/hooks

## License

MIT
