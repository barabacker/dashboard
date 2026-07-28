# Plan & Act Workflow

## Roles

- Architect (Claude chat / Project) = PLAN / REVIEW
- Claude Code = ACT
- superpowers = execution discipline
- Repository context transfer = optional (Claude Code reads the repo directly)

## Default workflow

1. Read the user prompt and requested `/superpowers:...` command.
2. Inspect relevant files before changing code.
3. Confirm assumptions against the repository.
4. Produce a plan when using `/superpowers:write-plan`.
5. Execute only within scope.
6. Add/update tests.
7. Run relevant validation.
8. Prepare return artifacts for Architect Review.

## Do not

- redesign the task without saying so
- silently broaden scope
- touch unrelated code
- skip tests for behavior changes
- hide uncertainty
- claim completion without validation

## Stop and ask

Stop if:
- actual code contradicts the brief
- multiple valid implementation paths appear
- the task requires a larger refactor
- backward compatibility risk appears
- tests reveal unexpected behavior
- assumptions are wrong
