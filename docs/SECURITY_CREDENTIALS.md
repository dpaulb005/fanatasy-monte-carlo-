# Credential Handling & Incident Runbook

## Incident (2026-07-15): live ESPN cookies committed to git

**What happened.** `.env` containing live `ESPN_S2` and `ESPN_SWID` cookies was
committed to this repository (commits `76a6ff8`, `bb10528`, `c168d46`, `8e3808e`)
on branch `claude/fantasy-league-analysis-plan-wm8zke`. A working copy named
`.env copy.example` also held the live values. These cookies authenticate as the
account owner on espn.com.

**Repo-side remediation done (2026-07-15):**

- `.env` untracked via `git rm --cached` (local file preserved; `.gitignore`
  already excluded it — tracking predated the ignore rule).
- `.env copy.example` scrubbed to a sanitized stub.
- `scripts/check_secrets.sh` added and wired into `make check` and CI — fails
  the build if a `.env` file is tracked or any tracked file contains
  cookie-shaped ESPN values.

## ⚠️ HUMAN ACTION REQUIRED

1. **Rotate the cookies.** Log out of *all* ESPN sessions (espn.com → account →
   sign out everywhere) or change the ESPN account password. Either invalidates
   the leaked `espn_s2`/`SWID` pair. Then re-extract fresh cookies into `.env`
   (see `docs/CONNECT_YOUR_LEAGUE.md`).
2. **Decide on history cleanup.** The old values remain reachable in git
   history until rewritten. If this repo is (or ever becomes) pushed to a
   remote others can read, rewrite history:

   ```bash
   # from a fresh clone, using git-filter-repo (recommended over BFG here)
   pip install git-filter-repo
   git filter-repo --invert-paths --path .env
   # then force-push every branch and have all collaborators re-clone
   ```

   This rewrites commit hashes; do it deliberately. For a private, single-user,
   never-pushed repo, rotation (step 1) removes the actual risk and history
   rewrite is optional hygiene.

## Rules going forward

- Secrets live only in `.env` (gitignored, untracked). `.env.example` is the
  only committed template and must contain placeholders only.
- ESPN credentials are read at sync time only (`backend/config/settings.py`)
  and must never appear in logs, fixtures, exports, or API responses.
- `make check` and CI run `scripts/check_secrets.sh`; do not bypass it.
- Shareable exports (cards, reports) must not embed SWIDs or internal GUIDs.
