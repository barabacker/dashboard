# Review Protocol

At the end of every non-trivial task, prepare review artifacts for the Architect. Claude Code
runs these git commands directly; the repository-context file is optional and only needed when
the Architect cannot open the repo.

## Required artifacts (native git)

    git status --short > /tmp/task-status.txt
    git diff --stat > /tmp/task-diff-stat.txt
    git diff > /tmp/task.diff
    git branch --show-current > /tmp/task-branch.txt
    git log --oneline --decorate -20 > /tmp/task-log.txt

Fold these into `/tmp/task-review-report.md` together with: original objective, summary,
commands run, test output, risks, and open questions.

## Optional: focused repository context

Only when the Architect is a context-less chat. Pack changed and neighboring files:

    {
      git diff --name-only
      git diff --name-only | xargs -r dirname
    } | sort -u \
      | xargs -r git ls-files \
      | sort -u \
      | repomix --stdin --style xml --output /tmp/task-review-context.xml

If too broad, narrow manually:

    git ls-files path/to/relevant/files \
      | repomix --stdin --style xml --output /tmp/task-review-context.xml

## Return summary

Return:
- summary of changes
- commands run
- test output
- files changed
- known risks
- artifacts created
- whether an optional context file was generated
