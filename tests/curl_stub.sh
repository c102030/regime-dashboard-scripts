#!/bin/bash
# Stands in for curl in the end-to-end checks: fails for URLs matching $BLOCK, passes the rest to the real curl.
for a in "$@"; do url="$a"; done
if [[ -n "$BLOCK" && "$url" =~ $BLOCK ]]; then echo "curl: (7) blocked by the test" >&2; exit 7; fi
exec "${REAL_CURL:-/usr/bin/curl}" "$@"
