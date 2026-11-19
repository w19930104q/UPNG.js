#!/usr/bin/env bash
# UPNG.js interop regression: reference decode, encode interop, roundtrip.
# Usage: test/run_all.sh   (from anywhere; operates on the repo root)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "== 1/3 generate reference sample matrix (Pillow + spec writer) =="
python3 "$ROOT/test/gen_refs.py" "$ROOT/test/refs"

echo "== 2/3 UPNG.js decode / roundtrip / encode (node) =="
node "$ROOT/test/interop.js" "$ROOT/test/refs" "$ROOT/test/out"

echo "== 3/3 verify UPNG.js encoder output with Pillow =="
python3 "$ROOT/test/check_encode.py" "$ROOT/test/refs" "$ROOT/test/out"

echo "ALL INTEROP CHECKS PASSED"
