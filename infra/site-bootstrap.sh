#!/usr/bin/env bash
# One-shot site bootstrap (D19): create the Pages project, deploy web/dist, attach ephemera.space
# with its DNS record, and set the GitHub Actions secrets so every later push to main that touches
# web/dist deploys itself (.github/workflows/deploy-site.yml). Deploys go through our own
# direct-upload client (infra/cf_site.py) - wrangler is deliberately not used: verified 31 Aug
# 2026 that it resolves its target account from machine-level state (an employer login) and
# ignores CLOUDFLARE_ACCOUNT_ID for pages deploy.
. "$(dirname "${BASH_SOURCE[0]}")/guard_cf.sh"

_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${_repo}"

python infra/cf_site.py project
python infra/cf_site.py deploy
python infra/cf_site.py domain

gh secret set CLOUDFLARE_API_TOKEN --repo Kira-Ryan/ephemera --body "${CLOUDFLARE_API_TOKEN}"
gh secret set CLOUDFLARE_ACCOUNT_ID --repo Kira-Ryan/ephemera --body "${CLOUDFLARE_ACCOUNT_ID}"
echo "site-bootstrap: done - https://ephemera.space (DNS may take a minute)" >&2
