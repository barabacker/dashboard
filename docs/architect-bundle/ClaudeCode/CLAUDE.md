# CLAUDE.md

Claude Code reads this file automatically at the start of every session (project memory).
Manage it with `/init` and `/memory`. You are working in this repository as an engineer, not
just a coder.

## Required reading

Before non-trivial work, read:

- `docs/agent/engineering_principles.md`
- `docs/agent/plan_act_workflow.md`
- `docs/agent/review_protocol.md`
- `docs/agent/task_continuity.md`

## New services

For greenfield service work, follow:

- `docs/agent/new_service_architecture.md`
- `docs/agent/engineering_principles.md`

Start with an Architecture Baseline before implementation.
Prefer simple modular service architecture with DDD-lite modeling.
Do not introduce heavyweight architecture unless justified by domain or operational complexity.

## Core rules

- Prefer minimal, explicit, maintainable changes.
- Do not broaden scope silently.
- Preserve existing architecture and style unless the task explicitly changes it.
- Separate domain logic from transport, persistence, side effects, and framework glue.
- Make state, time, retries, ordering, and idempotency explicit.
- Add or update tests for changed behavior.
- Run relevant validation.
- Report what changed, what was tested, and what remains risky.
- Stop and ask if the implementation contradicts the brief or requires a larger refactor.

## superpowers

Use the requested `/superpowers:...` skill from the prompt (superpowers plugin). For non-trivial
work, prefer plan before execution. If the plugin is not installed, follow the same
brainstorm -> plan -> execute discipline manually.

## Notes

- This file is `CLAUDE.md` (Claude Code's native memory). If you also use tools that read
  `AGENTS.md`, keep them in sync or symlink one to the other.
- Personal, cross-project rules live in `~/.claude/CLAUDE.md`; this project file governs this repo.
