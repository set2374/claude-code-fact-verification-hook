# Contributing

This project exists to improve factual-verification behavior in Claude Code through host-native hooks.

## Good first contributions

- Improve the prompt classifier so it catches more stale-fact scenarios without over-triggering.
- Add more tests around `last_assistant_message` and transcript fallbacks.
- Expand install docs for macOS and Linux.
- Tune trusted MCP defaults for common public servers.
- Add optional telemetry or debug logging that stays off by default.

## Ground rules

- Keep the project standalone. No private framework dependencies.
- Prefer positive behavior rules over giant negative prompt blocks.
- Do not add proprietary connectors, credentials, or private MCP names.
- Favor small, reviewable PRs with a clear before/after behavior description.

## Development

Run the smoke test:

```bash
python scripts/smoke_test.py
```

Syntax-check the hooks:

```bash
python -m py_compile hooks/common.py hooks/fact_prompt_gate.py hooks/track_verification.py hooks/verification_stop_gate.py
```
