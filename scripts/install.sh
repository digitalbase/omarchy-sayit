#!/usr/bin/env bash
set -euo pipefail
root="$(dirname -- "$(dirname -- "$(realpath -- "$0")")")"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.config/systemd/user"
target="$HOME/.local/bin/sayit"
if [[ -e "$target" && "$(realpath -- "$target")" != "$root/bin/sayit" ]]; then
  echo "Refusing to replace existing $target" >&2
  exit 1
fi
ln -sfn "$root/bin/sayit" "$target"
cp "$root/integration/omarchy-sayit.desktop" "$HOME/.local/share/applications/omarchy-sayit.desktop"
python - "$root" <<'PY'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
# Escape the absolute path for systemd's ExecStart parser and specifier expansion.
exe = str(root / 'bin/sayit').replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
unit = f'''[Unit]
Description=SayIt local speech service
PartOf=graphical-session.target
After=graphical-session.target

[Service]
ExecStart="{exe}" daemon
Restart=on-failure
RestartSec=3
UMask=0077
Environment=XDG_RUNTIME_DIR=%t

[Install]
WantedBy=graphical-session.target
'''
path = pathlib.Path.home() / '.config/systemd/user/sayit.service'
if path.exists() and path.read_text() != unit:
    raise SystemExit(f'Refusing to overwrite {path}; inspect it first')
path.write_text(unit)
PY
systemctl --user daemon-reload
systemctl --user enable --now sayit.service
echo "SayIt installed. Suggested shortcuts: $root/integration/bindings.lua"

