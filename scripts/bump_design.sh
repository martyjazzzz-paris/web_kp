#!/usr/bin/env bash
# Увеличить версию дизайна во всех нужных файлах.
# Использование: ./scripts/bump_design.sh 61 v61-top-split
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
NEW="${1:-}"
NEW_MARK="${2:-v${NEW}-top-split}"

if [[ -z "$NEW" ]] || ! [[ "$NEW" =~ ^[0-9]+$ ]]; then
  echo "Usage: $0 <version> [design-mark]" >&2
  echo "Example: $0 61 v61-top-split" >&2
  exit 1
fi

OLD="$(python3 - <<PY
import json
from pathlib import Path
print(json.loads(Path("${ROOT}/DESIGN_BASELINE.json").read_text())["version"])
PY
)"
STYLES="${ROOT}/static/styles.css"

if [[ "$NEW" -le "$OLD" ]]; then
  echo "Новая версия должна быть > ${OLD}" >&2
  exit 1
fi

perl -pi -e "s/--design-version: ${OLD}/--design-version: ${NEW}/" "$STYLES"
perl -pi -e "s/design-mark: v${OLD}-top-split/design-mark: ${NEW_MARK}/" "$STYLES"
perl -pi -e "s/KP Maker — v${OLD}/KP Maker — v${NEW}/" "$STYLES"

for f in templates/index.html main.py review_routes.py; do
  perl -pi -e "s/styles\\.css\\?v=${OLD}/styles.css?v=${NEW}/g" "${ROOT}/${f}"
done

python3 - <<PY
import json
from pathlib import Path
p = Path("${ROOT}/DESIGN_BASELINE.json")
d = json.loads(p.read_text())
d["version"] = int("${NEW}")
d["mark"] = "${NEW_MARK}"
d["cache_bust_value"] = "${NEW}"
d["required_markers"]["styles.css"][0] = f"design-mark: ${NEW_MARK}"
d["required_markers"]["styles.css"][1] = f"--design-version: ${NEW}"
d["required_markers"]["index.html"][1] = f"styles.css?v=${NEW}"
p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
PY

echo "Bumped ${OLD} → ${NEW}. Запустите: ./scripts/verify_baseline.sh"
