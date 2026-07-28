# Architect — Plan & Review to Claude Code

Adapted from the "Architect — Plan & Review to Codex" bundle. Same workflow, retargeted at
Claude Code as the executor.

## Roles
- **Architect** = PLAN / REVIEW. A Claude chat or a Claude **Project** loaded with the files
  in `knowledge_files/`. Helps you think before implementation and reviews results.
- **Claude Code** = ACT. Executes in the repository, using the harness in `ClaudeCode/`.
- **superpowers** = execution discipline (Claude Code plugin). Briefs start with one
  `/superpowers:...` command.
- **Repository context** = optional. Claude Code reads the repo natively; Repomix is only a
  fallback for a context-less Architect chat.

## How to install
1. **Architect (Claude Project):** paste `Instruction.md` into the Project's custom
   instructions; add everything under `knowledge_files/` as Project knowledge; optionally add
   `conversation_starters.md` as starter prompts.
2. **Claude Code harness (in your repo):** copy `ClaudeCode/CLAUDE.md` to your repo root as
   `CLAUDE.md` (Claude Code reads it automatically every session; `/init` and `/memory` manage
   it), and copy `ClaudeCode/docs/agent/` to `docs/agent/`.
3. **superpowers:** ensure the plugin is installed in Claude Code (`/plugin install ...`) and
   confirm the command names match; otherwise replace `/superpowers:*` with plain phase
   directives or local `.claude/commands/*.md`.

## What changed vs the Codex version
- `AGENTS.md` → `CLAUDE.md` (Claude Code's native memory file).
- `Codex intelligence: low|medium|high|extra high` → a **Model + Thinking** pair
  (`/model` choice + `think` / `think hard` / `ultrathink`). See `knowledge_files/modes_and_commands.md`.
- Repomix demoted from required to **optional** context transfer.
- `repomix_context_protocol.md` → `context_protocol.md`; `repomix_review_protocol.md` →
  `review_protocol.md` (Claude Code emits git review artifacts natively).
