#!/usr/bin/env bash
# Проверка: локальные файлы соответствуют DESIGN_BASELINE.json
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASELINE="${ROOT}/DESIGN_BASELINE.json"
STYLES="${ROOT}/static/styles.css"
INDEX="${ROOT}/templates/index.html"

if [[ ! -f "$BASELINE" ]]; then
  echo "Нет DESIGN_BASELINE.json" >&2
  exit 1
fi

VER="$(python3 - <<PY
import json
from pathlib import Path
print(json.loads(Path("${BASELINE}").read_text())["version"])
PY
)"
MARK="$(python3 - <<PY
import json
from pathlib import Path
print(json.loads(Path("${BASELINE}").read_text())["mark"])
PY
)"
CACHE="$(python3 - <<PY
import json
from pathlib import Path
print(json.loads(Path("${BASELINE}").read_text())["cache_bust_value"])
PY
)"

fail() { echo "BASELINE FAIL: $*" >&2; exit 1; }

grep -Fq "design-mark: ${MARK}" "$STYLES" || fail "styles.css: нет design-mark ${MARK}"
grep -F -- "--design-version: ${VER};" "$STYLES" >/dev/null || fail "styles.css: нет --design-version: ${VER}"
grep -Fq '.top-split' "$STYLES" || fail "styles.css: нет .top-split"
grep -Fq '.btn-remove-row' "$STYLES" || fail "styles.css: нет .btn-remove-row"

grep -Fq 'class="top-split"' "$INDEX" || fail "index.html: нет top-split"
grep -Fq "styles.css?v=${CACHE}" "$INDEX" || fail "index.html: нет styles.css?v=${CACHE}"
grep -Fq 'id="reload-page-btn"' "$INDEX" || fail "index.html: нет reload-page-btn"
grep -Fq 'dashboard-grid' "$INDEX" && fail "index.html: найден dashboard-grid (старая вёрстка!)"

for f in main.py review_routes.py; do
  grep -Fq "styles.css?v=${CACHE}" "${ROOT}/${f}" || fail "${f}: нет styles.css?v=${CACHE}"
done

echo "BASELINE OK — design v${VER} (${MARK})"
