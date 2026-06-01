#!/usr/bin/env bash
# Устарел: rsync --delete + docker build откатывал дизайн.
exec "$(dirname "$0")/deploy.sh"
