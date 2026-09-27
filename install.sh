#!/bin/sh
# Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
set -eu
case "$(uname -s)" in
  Darwin|Linux) ;;
  *) printf '%s\n' 'Use install.ps1 on Windows (WSL2).' >&2; exit 1 ;;
esac
command -v node >/dev/null 2>&1 || { printf '%s\n' 'Install Node.js 22.19 or newer from https://nodejs.org/ then run this command again.' >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { printf '%s\n' 'npm is required; use the official Node.js installation.' >&2; exit 1; }
media_install_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec node "$media_install_dir/agent-plugin/scripts/install.mjs" "$@"
