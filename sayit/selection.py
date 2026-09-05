"""Read only on invocation. Never synthesize copy shortcuts or monitor content."""
import subprocess


def read_selection(clipboard=False):
    cmd = ["wl-paste", "--no-newline", "--type", "text"]
    if not clipboard:
        cmd.append("--primary")
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=3, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        kind = "clipboard" if clipboard else "selection"
        raise ValueError(f"No readable {kind}. Copy the text and use 'sayit clipboard' if the app does not expose a Wayland selection.") from exc
    text = result.stdout.decode("utf-8").strip()
    if not text:
        raise ValueError("The selected text is empty")
    return text

