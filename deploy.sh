#!/bin/sh
# Деплой на прод. См. WORKFLOW.md
exec "$(dirname "$0")/fix_prod_now.sh"
