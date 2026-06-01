#!/usr/bin/env bash
# Сравнивает локальный дизайн с тем, что отдаёт прод.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STYLES="${ROOT}/static/styles.css"
PROD_URL="${PROD_URL:-http://72.56.237.74}"

echo "=== Локально: ${STYLES} ==="
grep -E 'design-version:|design-mark|\.top-split' "${STYLES}" | head -5
if grep -Fq '.btn-remove-row' "${STYLES}"; then echo "OK btn-remove-row"; else echo "MISSING btn-remove-row"; fi
if grep -Fq 'dashboard-grid' "${ROOT}/templates/index.html" && grep -Fq 'top-split' "${ROOT}/templates/index.html"; then
  echo "HTML: top-split (новый) + dashboard-grid в CSS только как запас"
elif grep -Fq 'top-split' "${ROOT}/templates/index.html"; then
  echo "OK HTML top-split"
else
  echo "HTML: НЕТ top-split — старая вёрстка!"
fi
grep 'styles.css?v=' "${ROOT}/templates/index.html" | head -1

echo ""
echo "=== Прод: ${PROD_URL} ==="
PROD_CSS="$(curl -sS --connect-timeout 12 "${PROD_URL}/static/styles.css" || true)"
if [[ -z "${PROD_CSS}" ]]; then
  echo "Не удалось скачать CSS с прода"
  exit 1
fi
echo "$PROD_CSS" | grep -E 'design-version:|design-mark' | head -3
if echo "$PROD_CSS" | grep -Fq '.top-split'; then echo "OK prod .top-split"; else echo "PROD СТАРЫЙ: нет .top-split"; fi
if echo "$PROD_CSS" | grep -Fq '.btn-remove-row'; then echo "OK prod btn-remove-row"; else echo "PROD СТАРЫЙ: нет btn-remove-row"; fi
curl -sS --connect-timeout 12 "${PROD_URL}/" | grep -o 'styles.css?v=[0-9]*' | head -1 || true
