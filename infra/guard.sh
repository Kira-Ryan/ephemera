#!/usr/bin/env bash
# Ephemera account guard (D02, CLAUDE.md rule 2). Every script under infra/ sources this as its
# first non-comment line. It refuses to run unless the ACTIVE AWS identity's account ID is on the
# personal allowlist in infra/personal.env (gitignored; template in personal.env.example).
#
# There is no override flag, environment variable or argument, by design: this machine's default
# AWS profile belongs to an employer account, and the whole value of the project is that no
# employer infrastructure ever touches it. An empty or missing allowlist is a refusal, not a pass.
set -euo pipefail

_guard_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "${_guard_dir}/personal.env" ]; then
    echo "guard: ${_guard_dir}/personal.env is missing - copy personal.env.example and fill it in" >&2
    exit 1
fi
# shellcheck source=/dev/null
. "${_guard_dir}/personal.env"

if [ -z "${EPHEMERA_AWS_ACCOUNT_IDS:-}" ]; then
    echo "guard: EPHEMERA_AWS_ACCOUNT_IDS is empty - an empty allowlist is a refusal, not a pass" >&2
    exit 1
fi

_acct="$(aws sts get-caller-identity --query Account --output text)" || {
    echo "guard: 'aws sts get-caller-identity' failed - no identity, no infrastructure action" >&2
    exit 1
}

case " ${EPHEMERA_AWS_ACCOUNT_IDS} " in
    *" ${_acct} "*)
        echo "guard: AWS account ${_acct} is on the personal allowlist - proceeding" >&2
        ;;
    *)
        echo "guard: REFUSED - active AWS account ${_acct} is NOT on the personal allowlist" >&2
        echo "guard: allowed: ${EPHEMERA_AWS_ACCOUNT_IDS}. If this is the employer profile, switch" >&2
        echo "guard: with AWS_PROFILE; if it is a new personal account, add its ID to personal.env." >&2
        exit 1
        ;;
esac
