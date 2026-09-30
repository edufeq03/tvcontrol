#!/usr/bin/env bash
# Script legado mantido para retrocompatibilidade. Redirecionando para install.sh...
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/install.sh" "$@"
