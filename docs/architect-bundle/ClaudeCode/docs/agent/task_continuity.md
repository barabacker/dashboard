# Task Continuity Protocol

Use this when a task may span multiple Claude Code or Architect sessions.

## Task state file

For non-trivial work, create or update:

    .agent/tasks/<task-id>/state.md

If `.agent/` is not desired in the repo, use:

    /tmp/<task-id>-state.md

## state.md structure

# Task State

## Objective
What we are trying to achieve.

## Current phase
brainstorm / write-plan / execute / review / follow-up

## Decisions made
Short list of accepted design decisions.

## Current assumptions
What is assumed and should be verified.

## Files touched
List of changed files.

## Tests / validation
What was run and results.

## Open questions
What is unresolved.

## Next action
The next concrete step.

## Artifacts
Paths to diff, status, reports (and optional context).

## Last known good point
Branch, commit, or state before risky changes.

## Rules

Keep this file short.
Use it as a pointer, not a full transcript.
Update it at the end of each substantial session.
