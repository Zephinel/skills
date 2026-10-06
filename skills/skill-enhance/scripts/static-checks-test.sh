#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

for script in "$ROOT"/scripts/*.sh; do
  bash -n "$script"
done

python3 -m py_compile \
  "$ROOT/assets/append-memory-entry-template.py" \
  "$ROOT/assets/append-memory-template.py" \
  "$ROOT/scripts/run-eval-cases.py" \
  "$ROOT"/scripts/stage3_*.py

python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])


def reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


for path in sorted(root.rglob("*.json")):
    json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)
PY

echo "skill-enhance static checks passed"
