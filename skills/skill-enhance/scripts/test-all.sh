#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CACHE_ROOT="$(mktemp -d)"
trap 'rm -rf "$CACHE_ROOT"' EXIT
export PYTHONPYCACHEPREFIX="$CACHE_ROOT"
for test_script in \
  static-checks-test.sh \
  self-test.sh \
  path-safety-regressions-test.sh \
  stage3-self-test.sh \
  stage3-reference-isolation-test.sh \
  stage3-no-skill-self-test.sh \
  stage3-review-regressions-test.sh \
  stage3-runtime-hardening-test.sh \
  full-review-regressions-test.sh \
  memory-root-binding-test.sh \
  lock-stress-test.sh
do
  echo "==> ${test_script}"
  bash "$ROOT/$test_script"
done
