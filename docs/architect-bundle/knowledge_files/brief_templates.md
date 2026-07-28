# Brief Templates

User-facing discussion is in Russian by default.
All Claude Code-ready briefs under `/superpowers:...` must be written in English.

Each brief starts with one command, then two effort lines:

    Model: opus | sonnet | haiku
    Thinking: none | think | think hard | ultrathink

---

## Brainstorm Brief Template

/superpowers:brainstorm

Model: opus
Thinking: think hard

# Brainstorm Brief

## Objective
## Current Context
## Facts
## Assumptions
## Key Unknowns
## Candidate Directions
## Decision Criteria
## Risks of Premature Implementation
## What Must Be Clarified Next

---

## Execution Brief Template for write-plan

/superpowers:write-plan

Model: opus
Thinking: think hard

# Execution Brief

## Objective
## Why
## Scope
## Non-goals
## Relevant Context
## Architecture Baseline
Use for greenfield/new-service tasks:
- chosen architecture style
- domain model boundaries
- module/layer structure
- source of truth
- state and side effects
- testing strategy
- observability
- documentation expectations
## Context pointers
- Follow `CLAUDE.md` if present (Claude Code reads it automatically).
- Follow repository `docs/agent/*` guidance if present.
- Claude Code reads the repo directly; see `context_protocol.md` if a context-less Architect
  needs a packed review package.
- For long tasks, update `.agent/tasks/<task-id>/state.md` if the repo uses this convention, or
  include a continuation summary in `task-review-report.md`.

## Facts
## Assumptions
## Likely Affected Areas
## Constraints / Guardrails
## Tests
## Validation
## Stop-and-Ask Conditions
## Risks
## Done When
## Return to Architect Review
After execution, return a compact review package:
1. `/tmp/task-review-report.md`
2. `/tmp/task.diff`
3. `/tmp/task-review-context.xml`  (optional)

---

## Execution Brief Template for execute-plan

/superpowers:execute-plan

Model: sonnet
Thinking: think

# Execution Brief

## Objective
## Why
## Scope
## Non-goals
## Relevant Context
## Architecture Baseline
Use for greenfield/new-service tasks:
- chosen architecture style
- domain model boundaries
- module/layer structure
- source of truth
- state and side effects
- testing strategy
- observability
- documentation expectations
## Context pointers
- Follow `CLAUDE.md` if present.
- Follow repository `docs/agent/*` guidance if present.
- See `context_protocol.md` for the optional review package.

## Facts
## Assumptions
## Likely Affected Areas
## Suggested Execution Sequence
## Constraints / Guardrails
## Tests
## Validation
## Stop-and-Ask Conditions
## Risks
## Done When
## Return to Architect Review
After execution, return a compact review package:
1. `/tmp/task-review-report.md`
2. `/tmp/task.diff`
3. `/tmp/task-review-context.xml`  (optional)
