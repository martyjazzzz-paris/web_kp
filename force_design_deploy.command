#!/bin/bash
cd "$(dirname "$0")"
echo "Введите пароль root VPS (не отображается при export — вставьте в следующую строку):"
read -rs DEPLOY_PASS
export DEPLOY_PASS
echo ""
./deploy.sh
read -p "Enter для закрытия..."
