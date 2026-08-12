#!/usr/bin/env bash
# Double-clickable JARVIS launcher.
# Finder runs this in Terminal; it just hands off to start.sh in the same folder.
cd "$(dirname "${BASH_SOURCE[0]}")" || exit 1
exec ./start.sh
