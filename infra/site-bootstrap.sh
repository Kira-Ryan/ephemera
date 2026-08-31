#!/usr/bin/env bash
# One-shot site bootstrap (D19): create the Pages project, first deploy of web/dist, attach
# ephemera.space with its DNS record, and set the GitHub Actions secrets so every later push to
# main that touches web/dist deploys itself (.github/workflows/deploy-site.yml).
. "$(dirname "${BASH_SOURCE[0]}")/guard_cf.sh"

_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${_repo}"

python infra/cf_site.py project
npx --yes wrangler pages deploy web/dist --project-name ephemera --branch main --commit-dirty=true
python infra/cf_site.py domain

gh secret set CLOUDFLARE_API_TOKEN --repo Kira-Ryan/ephemera --body "${CLOUDFLARE_API_TOKEN}"
gh secret set CLOUDFLARE_ACCOUNT_ID --repo Kira-Ryan/ephemera --body "${CLOUDFLARE_ACCOUNT_ID}"
echo "site-bootstrap: done - https://ephemera.space (DNS may take a minute) and https://ephemera.pages.dev" >&2
