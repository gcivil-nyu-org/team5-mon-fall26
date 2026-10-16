#!/usr/bin/env bash
# Copies the Epic 1 issue and its user stories from GitHub into docs/.
# Needs the GitHub CLI (https://cli.github.com) and `gh auth login` once.
# Run from the repo root: bash scripts/sync-stories.sh
set -euo pipefail

REPO="gcivil-nyu-org/team5-mon-fall26"
mkdir -p docs/stories

write_issue() {  # $1 = issue number, $2 = output file
  gh issue view "$1" --repo "$REPO" --json number,title,body,state \
    --template '# #{{.number}} {{.title}}
Status on GitHub: {{.state}}

{{.body}}
' > "$2"
  echo "wrote $2"
}

write_issue 1 docs/epic-1.md
for pair in 3:US1 4:US2 5:US3 6:US4 7:US5 8:US6 9:US7 10:US8 11:US9; do
  write_issue "${pair%%:*}" "docs/stories/${pair##*:}.md"
done
# Add US0 (data import) files by hand once the issue numbers exist, for example:
#   write_issue 12 docs/stories/US0a.md
