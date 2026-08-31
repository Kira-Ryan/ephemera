#!/usr/bin/env bash
# Smallest guarded script: prints the active AWS identity IF the guard lets it through. Serves as
# the template every other infra script copies - guard first, work after.
. "$(dirname "${BASH_SOURCE[0]}")/guard.sh"

aws sts get-caller-identity --output json
