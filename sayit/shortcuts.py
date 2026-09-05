"""Manage only SayIt's selection/clipboard bindings in the user's Hyprland Lua."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import time

FIELDS = ("selection_shortcut", "clipboard_shortcut")
MODIFIERS = {"SUPER": 64, "CTRL": 4, "ALT": 8, "SHIFT": 1}
START = "-- BEGIN SAYIT SHORTCUTS"
END = "-- END SAYIT SHORTCUTS"
LEGACY = re.compile(r'^o\.bind\("([^"\n]+)", "(Read selected text|Read clipboard)", "sayit (selection|clipboard) --detach"\)\s*$', re.M)


def normalize(value):
    if not isinstance(value, str):
        raise ValueError("A shortcut must be text")
    if not value.strip():
        return ""
    parts = [p.strip().upper() for p in value.split("+")]
    mods, key = parts[:-1], parts[-1]
    if any(m not in MODIFIERS for m in mods) or len(set(mods)) != len(mods):
        raise ValueError("Use modifiers SUPER, CTRL, ALT and SHIFT, for example CTRL + F10")
    named_keys = {"SPACE", "RETURN", "ESCAPE", "TAB", "BACKSPACE", "DELETE", "INSERT",
                  "HOME", "END", "PAGE_UP", "PAGE_DOWN", "LEFT", "RIGHT", "UP", "DOWN",
                  "PRINT", "PAUSE", "MENU", "CAPS_LOCK", "NUM_LOCK", "SCROLL_LOCK"}
    if not (re.fullmatch(r"[A-Z0-9]|F(?:[1-9]|[12][0-9]|3[0-5])", key) or key in named_keys):
        raise ValueError("Use a key name such as F10, A, SPACE or RETURN")
    return " + ".join([m for m in MODIFIERS if m in mods] + [key])


def identity(shortcut):
    parts = normalize(shortcut).split(" + ")
    return sum(MODIFIERS[m] for m in parts[:-1]), parts[-1].casefold()


def render(original, selection, clipboard):
    cleaned = re.sub(r'(?ms)^' + START + r'\n.*?^' + END + r'\n?', '', original)
    cleaned = LEGACY.sub('', cleaned)
    lines = [START, "-- Managed by SayIt Settings. Other bindings are left alone."]
    for shortcut, action, label in ((selection, "selection", "Read selected text"), (clipboard, "clipboard", "Read clipboard")):
        if shortcut:
            lines += [f'hl.unbind({json.dumps(shortcut)})',
                      f'o.bind({json.dumps(shortcut)}, {json.dumps(label)}, "sayit {action} --detach")']
    lines += [END]
    return cleaned.rstrip() + "\n\n" + "\n".join(lines) + "\n"


def reload_config():
    subprocess.run(["hyprctl", "reload"], check=True, capture_output=True, text=True, timeout=10)
    errors = subprocess.run(["hyprctl", "configerrors"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
    if errors and errors != "ok":
        raise ValueError("Hyprland rejected the shortcut configuration: " + errors)


def check_conflicts(bindings, original, selection, clipboard):
    if selection and clipboard and selection == clipboard:
        raise ValueError("Selection and clipboard must use different shortcuts")
    owned = {identity(m[0]): m[1] for m in LEGACY.findall(original)}
    for shortcut in (selection, clipboard):
        if not shortcut:
            continue
        chord = identity(shortcut)
        for binding in bindings:
            existing = (binding.get("modmask", 0), str(binding.get("key", "")).casefold())
            if existing != chord:
                continue
            # Only replace the exact SayIt bindings present in this file.
            if (owned.get(chord) == binding.get("description") and not binding.get("release")
                    and not binding.get("submap")):
                continue
            description = binding.get("description") or binding.get("dispatcher") or "another action"
            raise ValueError(f"{shortcut} is already assigned to {description}. Choose another shortcut.")


@contextmanager
def apply(settings):
    selection, clipboard = [normalize(settings[k]) for k in FIELDS]
    folder = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "hypr"
    path = folder / "bindings.lua"
    if not path.exists():
        raise ValueError("Shortcut settings require Omarchy's ~/.config/hypr/bindings.lua")
    original = path.read_text()
    live = json.loads(subprocess.run(["hyprctl", "-j", "binds"], capture_output=True, text=True, check=True, timeout=10).stdout)
    check_conflicts(live, original, selection, clipboard)
    baseline = subprocess.run(["hyprctl", "configerrors"], capture_output=True, text=True, check=True, timeout=10).stdout.strip()
    if baseline and baseline != "ok":
        raise ValueError("Resolve the existing Hyprland configuration errors before changing shortcuts")
    updated = render(original, selection, clipboard)
    if updated == original:
        yield
        return
    path.with_name(path.name + f".bak-sayit-{time.time_ns()}").write_text(original)
    try:
        path.write_text(updated)
        reload_config()
        yield
    except BaseException:
        path.write_text(original)
        reload_config()
        raise
