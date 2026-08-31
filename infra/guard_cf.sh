#!/usr/bin/env bash
# Ephemera Cloudflare account guard (D02, D19). Sourced first by every infra script that touches
# Cloudflare. The wrangler OAuth login on the dev machine belongs to an EMPLOYER identity
# (verified 31 Aug 2026: an employer address, two employer accounts), so these scripts run ONLY with
# an explicit API token from infra/personal.env, exported so wrangler and raw API calls can never
# fall back to the ambient login. No override flag exists; an empty allowlist is a refusal.
set -euo pipefail

_guard_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "${_guard_dir}/personal.env" ]; then
    echo "guard_cf: ${_guard_dir}/personal.env is missing - copy personal.env.example and fill it in" >&2
    exit 1
fi
# shellcheck source=/dev/null
. "${_guard_dir}/personal.env"

for _v in CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID EPHEMERA_CF_ACCOUNT_IDS; do
    if [ -z "$(eval "echo \${${_v}:-}")" ]; then
        echo "guard_cf: ${_v} is empty in personal.env - a missing credential or allowlist is a refusal" >&2
        exit 1
    fi
done

case " ${EPHEMERA_CF_ACCOUNT_IDS} " in
    *" ${CLOUDFLARE_ACCOUNT_ID} "*) ;;
    *)
        echo "guard_cf: REFUSED - CLOUDFLARE_ACCOUNT_ID ${CLOUDFLARE_ACCOUNT_ID} is not on the personal allowlist (${EPHEMERA_CF_ACCOUNT_IDS})" >&2
        exit 1
        ;;
esac

export CLOUDFLARE_API_TOKEN CLOUDFLARE_ACCOUNT_ID

# The token must actually control the project's zone, and that zone must belong to the allowlisted
# account - a stale or copy-pasted-from-work token fails here, before any write happens. (The zone
# endpoint, not /accounts/{id}: a properly scoped token has Zone:Read on ephemera.space but no
# Account:Read, verified 31 Aug 2026.)
_resp="$(curl -sS -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    "https://api.cloudflare.com/client/v4/zones?name=ephemera.space")" || {
    echo "guard_cf: Cloudflare API unreachable - no verification, no action" >&2
    exit 1
}
echo "${_resp}" | python -c "
import json, os, sys
r = json.load(sys.stdin)
zones = r.get('result') or []
sys.exit(0 if r.get('success') and zones and zones[0]['account']['id'] == os.environ['CLOUDFLARE_ACCOUNT_ID'] else 1)
" || {
    echo "guard_cf: REFUSED - the token cannot see the ephemera.space zone under the allowlisted account (wrong account or wrong token scoping)" >&2
    exit 1
}

echo "guard_cf: Cloudflare account ${CLOUDFLARE_ACCOUNT_ID} verified against the personal allowlist - proceeding" >&2
