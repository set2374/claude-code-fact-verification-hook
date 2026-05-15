# Claude Code Fact Verification Hook

A standalone Claude Code hook set for stale facts, premature assertions, and "answer first, verify later" behavior in Claude Code, including the failure mode some users are now describing as an Opus 4.7 factual-verification problem.

If you found this while searching for any of the following, you are in the right place:

- Claude Code stale facts fix
- Claude Code verify before assert
- Claude Code fact checking hook
- Opus 4.7 fix for wrong factual answers
- Opus 4.7 not searching before answering
- Claude Code current info wrong
- Claude Code web search not triggered

The short version: this repo adds a verification-first gate so Claude Code is pushed toward:

- verify first
- assert second
- use a short verify-first preamble instead of premature analysis
- return a structured final answer with sources
- caveat explicitly when verification did not happen after a good-faith attempt

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

In practice, some users are experiencing this as:

- "Claude or Opus 4.7 sounded confident but answered from training knowledge"
- "Claude Code did not trigger web search because it thought it already knew"
- "The answer sounded current, but it was wrong or stale"

This project adds a lightweight forcing function using Claude Code's native hooks:

1. `UserPromptSubmit` classifies prompts that are likely to require factual verification.
2. `PostToolUse` records when Claude actually performed a meaningful verification step.
3. `Stop` blocks the turn from ending if Claude is about to make unsupported factual assertions without a verification step.
4. `Stop` also blocks verification-sensitive answers that ignore the required response structure.

## Design goals

- standalone
- no private framework dependencies
- positive instruction style
- minimal moving parts
- easy to fork and tune
- understandable as a practical fix for Claude Code and Opus 4.7 verification drift

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

- verification evidence exists and the response uses the required structure, or
- the response clearly says it is provisional or unverified after a verification attempt, or
- Claude is just asking a clarifying question

It blocks the turn if:

- verification-sensitive mode is active, and
- no meaningful verification evidence exists, or
- the response reads like a factual answer rather than a caveated answer, or
- the answer skips the required deployment-friendly structure

### 4. Response shape

For verification-sensitive prompts, the hook set now pushes Claude toward:

- one short sentence before research, if any
- then tool use
- then a final structured answer

Default structures:

- factual prompts:
  - `Bottom line:`
  - `Verified facts:`
  - `Sources:`
- theory-heavy / multi-claim prompts:
  - `Bottom line:`
  - `Verified facts:`
  - `Analysis:`
  - `Sources:`

## Is this an Opus 4.7 fix?

Partly, yes.

More precisely:

- this repo does not patch Anthropic's model weights
- it does not change Claude Code's native search heuristics
- it does add a host-side behavioral forcing function that is useful when Opus 4.7 or another Claude model answers factual questions from training knowledge too readily

So if you are looking for a practical Opus 4.7 workaround, guardrail, or mitigation for stale factual answers, this repo is aimed directly at that problem.


## Install

### 1. Clone the repo

```bash
git clone https://github.com/<your-username>/claude-code-fact-verification-hook.git
```

### 2. Copy the hooks somewhere stable

This repo assumes you will reference the hook scripts by absolute path from your Claude Code settings.

Recommended stable locations:

| Platform | Path |
|----------|------|
| Windows | `C:\Users\<you>\.claude\hooks\fact-verification\` |
| macOS | `/Users/<you>/.claude/hooks/fact-verification/` |
| Linux | `/home/<you>/.claude/hooks/fact-verification/` |

### 3. Optional: create a config file

Copy `config.example.json` to one of:

| Platform | Config location |
|----------|-----------------|
| Windows | `%APPDATA%\claude-code-fact-verification\config.json` |
| macOS | `~/.config/claude-code-fact-verification/config.json` |
| Linux | `~/.config/claude-code-fact-verification/config.json` |

Then set the environment variable:

```bash
# macOS / Linux
export FACT_VERIFICATION_CONFIG_PATH=~/.config/claude-code-fact-verification/config.json

# Windows (PowerShell)
$env:FACT_VERIFICATION_CONFIG_PATH = "$env:APPDATA\claude-code-fact-verification\config.json"
```

### 4. Register the hooks

Claude Code settings live in:

| Platform | Settings file |
|----------|--------------|
| Windows | `%APPDATA%\claude-code\settings.json` |
| macOS | `~/Library/Application Support/claude-code/settings.json` |
| Linux | `~/.config/claude-code/settings.json` |

Use `settings.example.json` as a starting point. Replace `<REPO_PATH>` with the absolute path where you cloned this repo.

**macOS / Linux example:**

```json
{
  "hooks": {
    "UserPromptSubmit": [{"command": "python3 /Users/you/.claude/hooks/fact-verification/hooks/fact_prompt_gate.py"}],
    "PostToolUse": [{"command": "python3 /Users/you/.claude/hooks/fact-verification/hooks/track_verification.py"}],
    "Stop": [{"command": "python3 /Users/you/.claude/hooks/fact-verification/hooks/verification_stop_gate.py"}]
  }
}
```

**Windows example:**

```json
{
  "hooks": {
    "UserPromptSubmit": [{"command": "python C:\\Users\\you\\.claude\\hooks\\fact-verification\\hooks\\fact_prompt_gate.py"}],
    "PostToolUse": [{"command": "python C:\\Users\\you\\.claude\\hooks\\fact-verification\\hooks\\track_verification.py"}],
    "Stop": [{"command": "python C:\\Users\\you\\.claude\\hooks\\fact-verification\\hooks\\verification_stop_gate.py"}]
  }
}
```

### 5. Restart Claude Code

Hook registration changes are safest after a restart or a fresh session.
## Quick smoke test

```bash
python scripts/smoke_test.py
```

The smoke test checks that:

- verification mode activates for a current/factual prompt
- an unsupported factual answer gets blocked
- a `Read` or `WebSearch` action can satisfy the gate
- caveat-only without verification is blocked
- unstructured answers are blocked even after verification
- structured answers with source links pass

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

## Search Notes

This project is intentionally written for people searching for:

- Claude Code factual verification hooks
- Claude Code fact checking
- Claude Code stale knowledge
- Claude Code not using web search
- Opus 4.7 verification fix
- Opus 4.7 stale facts
- Opus 4.7 current information workaround
- verify-before-assert hooks for Claude Code

## References

- Anthropic Claude Code hooks docs: https://docs.anthropic.com/en/docs/claude-code/hooks

## License

MIT
