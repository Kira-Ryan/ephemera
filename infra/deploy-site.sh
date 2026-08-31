#!/usr/bin/env bash
# Manual site deploy (normally unnecessary: pushing to main deploys via GitHub Actions).
. "$(dirname "${BASH_SOURCE[0]}")/guard_cf.sh"

_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${_repo}"
npx --yes wrangler pages deploy web/dist --project-name ephemera --branch main --commit-dirty=true
