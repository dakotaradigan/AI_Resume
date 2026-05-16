# CLAUDE.md

Claude-specific instructions for this repository.

Use `AGENTS.md` as the canonical project guide for architecture, commands, security rules, RAG behavior, and git policy. Keep repo-wide instructions there so Claude, Codex, and other coding agents work from the same source of truth.

## Evals

When asked to "kick off evals", "set up evals", or work on judge workflows, follow the protocol in `evals/CLAUDE.md`.

Before starting eval work, read:
- `evals/CLAUDE.md`
- `evals/docs/CORE_MENTAL_MODEL.md`
- Any relevant docs under `evals/docs/`

Judge prompts and eval scripts are code. Dataset and result files may contain PII and are gitignored; do not commit files in `evals/datasets/` or `evals/results/` without explicit user approval.

## Attribution

Do not add `Co-Authored-By` lines for Claude or other AI assistants unless the user explicitly asks.
