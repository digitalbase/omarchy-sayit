#!/usr/bin/env bash
set -euo pipefail
root="$(dirname -- "$(dirname -- "$(realpath -- "$0")")")"
config_root="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy"
plugin="$config_root/plugins/digitalbase.sayit"
omarchy plugin validate "$root/integration/omarchy-sayit"
if [[ -d "$plugin" ]]; then
  mkdir -p "$config_root/backups"
  cp -a "$plugin" "$config_root/backups/digitalbase.sayit.$(date +%s)"
fi
if [[ -f "$config_root/shell.json" ]]; then
  cp "$config_root/shell.json" "$config_root/shell.json.bak-sayit-$(date +%s)"
fi
mkdir -p "$plugin"
cp "$root/integration/omarchy-sayit/manifest.json" "$root/integration/omarchy-sayit/Panel.qml" "$plugin/"
omarchy-shell shell rescanPlugins
omarchy plugin enable digitalbase.sayit right --before omarchy.audio
