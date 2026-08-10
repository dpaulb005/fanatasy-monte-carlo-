#!/usr/bin/env bash
# Secret-scan guard: fails if staged/tracked files contain ESPN credential
# material. Run via `make check` and CI. Scans tracked files only — local
# .env stays on disk but must never be committed.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

fail=0

# 1) Credential-bearing filenames must not be tracked (templates are fine).
if git ls-files | grep -vE '^\.env\.example$' | grep -E '(^|/)\.env($| )' >/dev/null; then
  echo "FAIL: a .env file is tracked by git. Run: git rm --cached <file>" >&2
  fail=1
fi

# 2) Tracked content must not contain cookie-shaped ESPN values.
#    ESPN_S2 values are long URL-encoded blobs; SWIDs are brace-wrapped GUIDs.
pattern='ESPN_S2=[A-Za-z0-9%+/=]{80,}|ESPN_SWID=\{[0-9A-Fa-f-]{36}\}|SWID=\{[0-9A-Fa-f-]{36}\}'
if git grep -nE "$pattern" -- ':!scripts/check_secrets.sh' >/dev/null 2>&1; then
  echo "FAIL: tracked files contain ESPN credential-shaped values:" >&2
  git grep -lE "$pattern" -- ':!scripts/check_secrets.sh' >&2
  fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "secret scan: OK (no tracked credentials)"
fi
exit "$fail"
