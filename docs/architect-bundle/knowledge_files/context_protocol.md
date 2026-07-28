# Context Protocol

In the Architect -> Claude Code workflow, **Claude Code reads the repository directly**. The
executor never needs context packing. Context transfer matters only for the **Architect** when
it is a chat without repo access.

Use context transfer for:
- letting a context-less Architect understand an existing repository or service
- architectural analysis before planning
- debugging and investigation planning
- preparing better Claude Code briefs
- reviewing Claude Code results when the Architect cannot open the repo

Do not assume context packing is required. If the Architect has repo access (or the user pastes
the relevant files), skip this entirely.

Claude Code-facing instructions and review requirements should be written in English.

---

## Before planning

If the Architect has repository context (pasted files, or its own repo access):
- first build a mental map of the relevant code
- identify entry points, API routes, use cases, DB/repository layer, workers, clients, tests
  and config boundaries
- then choose the mode: Brainstorm, Investigation Planning, or Claude Code-ready Transition

If the Architect has no context:
- continue normally if the task is understandable without repo context
- otherwise ask for focused context (Repomix or `git`) and briefly explain why those paths or
  keywords are needed

---

## Option A — let Claude Code gather context (preferred)

Since Claude Code sees the repo, the simplest path is to ask Claude Code to produce the focused
context or summary itself, e.g. as part of a `/superpowers:write-plan` step, or with plain git:

    git ls-files path/to/a path/to/b tests/relevant_test.py

Claude Code reads those files directly — no packing step.

---

## Option B — Repomix packing (fallback for a context-less Architect)

When the Architect is a chat that cannot open the repo, pack focused context and paste/upload it.

Preferred format is XML:

    repomix --style xml --output /tmp/context.xml

For large repositories, inspect token distribution first:

    repomix --token-count-tree

For broad service familiarization:

    repomix --style xml --output /tmp/service-context.xml

or compressed:

    repomix --compress --style xml --output /tmp/service-compressed-context.xml

Focused context for known paths:

    git ls-files \
      path/to/a \
      path/to/b \
      tests/relevant_test.py \
      | repomix --stdin --style xml --output /tmp/task-context.xml

Focused context when relevant files are unknown:

    rg -l "keyword1|keyword2|keyword3" \
      | repomix --stdin --style xml --output /tmp/task-context.xml

If the search result is too broad, narrow the keywords or manually choose the relevant paths.

---

## Review requirement

For every non-trivial Claude Code task, request review artifacts unless the user disables
review. Claude Code generates the git artifacts natively; the repo-context file is optional.

Return no more than 3 files:

1. `/tmp/task-review-report.md`
2. `/tmp/task.diff`
3. `/tmp/task-review-context.xml`  (optional — only if the Architect has no repo access)

Do not request many separate artifact files unless the user explicitly asks for them.

---

## Review file 1: task-review-report.md

Should contain:
- original brief or short objective
- result summary
- commands run
- test output
- git status
- git diff stat
- current branch
- recent git log
- known risks
- open questions
- continuation summary / task-state notes for long tasks, if relevant

Recommended command (Claude Code can run this itself):

    {
      echo "# Task Review Report"
      echo
      echo "## Original Objective / Brief"
      echo "TODO: paste the short objective or original brief here."
      echo
      echo "## Summary"
      echo "TODO: summarize changes here."
      echo
      echo "## Commands Run"
      echo "TODO: paste commands and results here."
      echo
      echo "## Test Output"
      echo "TODO: paste test output here."
      echo
      echo "## Git Status"
      git status --short
      echo
      echo "## Git Diff Stat"
      git diff --stat
      echo
      echo "## Branch"
      git branch --show-current
      echo
      echo "## Recent Log"
      git log --oneline --decorate -20
      echo
      echo "## Risks / Open Questions"
      echo "TODO: list known risks or unresolved questions."
      echo
      echo "## Continuation Notes"
      echo "TODO: for long tasks, add next action, current phase, and state summary."
    } > /tmp/task-review-report.md

---

## Review file 2: task.diff

    git diff > /tmp/task.diff

---

## Review file 3: task-review-context.xml (optional)

Only needed when the Architect cannot open the repo. Focused context for changed and neighboring
files:

    {
      git diff --name-only
      git diff --name-only | xargs -r dirname
    } | sort -u \
      | xargs -r git ls-files \
      | sort -u \
      | repomix --stdin --style xml --output /tmp/task-review-context.xml

Narrow manually if too broad:

    git ls-files path/to/relevant/files \
      | repomix --stdin --style xml --output /tmp/task-review-context.xml

For very large contexts, add `--compress`.

---

## Return to Architect Review

Every non-trivial Claude Code brief should usually end with:

    ## Return to Architect Review

Ask Claude Code / the user to return the compact package:

1. `/tmp/task-review-report.md`
2. `/tmp/task.diff`
3. `/tmp/task-review-context.xml`  (optional)

Do not prepare a follow-up brief immediately after review unless follow-up work is actually
needed. For non-trivial follow-ups, prefer `/superpowers:write-plan`; use
`/superpowers:execute-plan` only for small, clear, low-risk fixes.
