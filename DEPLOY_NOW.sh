#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -z "${DEPLOY_PASS:-}" ]]; then
  echo 'export DEPLOY_PASS="пароль root"' >&2
  exit 1
fi
exec ./deploy.sh
