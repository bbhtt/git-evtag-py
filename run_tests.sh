#!/usr/bin/env bash
set -euo pipefail

export KEY_URL="https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xd26d753395009db2b3b260940c3251a24745e484"
export EVTAG_NO_GPG_SIGN="true"

if [[ -n "${TEST_CMD:-}" ]]; then
    eval "$TEST_CMD"
elif command -v uv >/dev/null 2>&1; then
    uv run --frozen -q pytest --ff --exitfirst
else
    pytest --ff --exitfirst
fi

unset KEY_URL EVTAG_NO_GPG_SIGN
