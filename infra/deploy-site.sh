#!/usr/bin/env bash
# Manual site deploy (normally unnecessary: pushing to main deploys via GitHub Actions).
# Uses infra/cf_site.py's direct-upload client; wrangler is deliberately not used (see
# site-bootstrap.sh for the 31 Aug 2026 finding).
. "$(dirname "${BASH_SOURCE[0]}")/guard_cf.sh"

_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${_repo}"
python infra/cf_site.py deploy
