#!/usr/bin/env bash
# Собирает byte-for-byte воспроизводимый kb-architect.skill.
set -euo pipefail

cd "$(dirname "$0")"

exec python3 build.py
