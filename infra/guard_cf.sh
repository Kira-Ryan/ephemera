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

# The zone answer is JSON, so reading it needs an interpreter. A stock Debian or Ubuntu host has
# no `python` command at all, only `python3`: a bare `python` there exits 127, and that failure was
# caught by the zone check's own || block, which printed a refusal worded as a failed zone binding
# while the binding had never been evaluated. Resolve the interpreter before the API call and
# refuse in its own words if there is none, so the two refusals can never be read as one again.
_py=""
for _cand in python3 python; do
    if command -v "${_cand}" >/dev/null 2>&1; then
        _py="${_cand}"
        break
    fi
done
if [ -z "${_py}" ]; then
    echo "guard_cf: no python3 or python on PATH - the zone binding cannot be checked, so nothing runs" >&2
    exit 1
fi

# The token must actually control the project's zone, and that zone must belong to the allowlisted
# account - a stale or copy-pasted-from-work token fails here, before any write happens. (The zone
# endpoint, not /accounts/{id}: a properly scoped token has Zone:Read on ephemera.space but no
# Account:Read, verified 31 Aug 2026.)
_resp="$(curl -sS -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" \
    "https://api.cloudflare.com/client/v4/zones?name=ephemera.space")" || {
    echo "guard_cf: Cloudflare API unreachable - no verification, no action" >&2
    exit 1
}
# The interpreter prints the owning account instead of exiting on the comparison, so each refusal
# below names the id the API answer carried - something no run that skipped the answer can print.
_owner="$(echo "${_resp}" | "${_py}" -c "
import json, sys
r = json.load(sys.stdin)
zones = r.get('result') or []
print(zones[0]['account']['id'] if r.get('success') and zones else '')
")" || {
    echo "guard_cf: REFUSED - ${_py} could not read the Cloudflare zone answer, so the zone binding is unverified" >&2
    exit 1
}
if [ -z "${_owner}" ]; then
    echo "guard_cf: REFUSED - this token cannot see the ephemera.space zone (wrong account, or a token scoped somewhere else)" >&2
    exit 1
fi
if [ "${_owner}" != "${CLOUDFLARE_ACCOUNT_ID}" ]; then
    echo "guard_cf: REFUSED - the ephemera.space zone belongs to account ${_owner}, not to the ${CLOUDFLARE_ACCOUNT_ID} this run is using" >&2
    exit 1
fi

echo "guard_cf: Cloudflare account ${CLOUDFLARE_ACCOUNT_ID} verified against the personal allowlist - proceeding" >&2
