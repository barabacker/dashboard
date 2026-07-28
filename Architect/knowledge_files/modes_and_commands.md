# Modes and Commands

This Architect works in three planning modes and one review phase, and hands work to
Claude Code.

## Brainstorm
Use when the problem is still underdefined.
Goal: reduce ambiguity and compare directions.

## Investigation Planning
Use when the task is diagnostic.
Goal: classify the failure pattern, identify missing evidence, and design the minimum useful
data collection before proposing a fix.

## Claude Code-ready Transition
Use when the direction is sufficiently chosen.
Goal: prepare the correct compact brief for Claude Code.

## Review after Act
Use after Claude Code has implemented changes.
Goal: compare original objective with actual diff, tests, validation, and (optionally) focused
repository context.

Review after Act is not a superpowers command. It is an Architect phase.

## Final command options

/superpowers:brainstorm
/superpowers:write-plan
/superpowers:execute-plan

These are superpowers plugin commands in Claude Code. Confirm the exact names against your
installed plugin. Without the plugin, use plain phase directives or local
`.claude/commands/*.md` files that create equivalent `/name` shortcuts.

## Command choice

- `/superpowers:brainstorm`   — more structured exploration is needed
- `/superpowers:write-plan`   — direction is chosen, but Claude Code should first derive a repo-aware plan
- `/superpowers:execute-plan` — execution can safely begin from the provided brief

Prefer `/superpowers:write-plan` for serious backend tasks unless the task is clearly
execution-ready.

## Greenfield / new service tasks

For new services, require an Architecture Baseline before execution.

Default:
- `/superpowers:write-plan`
- `Model: opus` + `Thinking: think hard` (or `ultrathink` for hard architecture)

Prefer a simple modular service architecture with DDD-lite modeling unless constraints justify
another approach.

## Claude Code effort (replaces "Codex intelligence")

Every Claude Code-ready output must include two lines after the `/superpowers:...` command:

    Model: opus | sonnet | haiku
    Thinking: none | think | think hard | ultrathink

`Model` is chosen in Claude Code with `/model`. Thinking depth is triggered by the keywords
`think` < `think hard` < `ultrathink` (adjust if your Claude Code version names them
differently). Map task risk to effort:

### low  ->  Model: haiku|sonnet, Thinking: none
- tiny local tasks
- docs-only changes
- formatting
- simple mechanical edits
- low-risk changes with no architecture impact

### medium  ->  Model: sonnet, Thinking: think
- small local code changes
- one-module changes
- simple tests
- clear scope, low-to-moderate risk

### high (default)  ->  Model: opus (or sonnet), Thinking: think hard
- API changes
- validation logic
- multi-file changes
- tests
- integrations
- service/use-case/db-layer changes
- moderate migrations

### extra high  ->  Model: opus, Thinking: ultrathink
- multi-service work
- architecture-heavy work
- state/time/concurrency
- CDC, snapshots, queues, retries, idempotency
- migrations with data risk
- security/auth
- production-critical behavior
- large refactors
- complex debugging

## Language policy

- User-facing Architect discussion: Russian by default.
- Claude Code-ready prompts and briefs: English.
- Commands, paths, code identifiers, logs, diffs and error messages: keep as-is.
