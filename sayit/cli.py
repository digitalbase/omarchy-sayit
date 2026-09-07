import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from .catalog import installed, model_by_id, models
from .paths import data_dir
from .service import call


def parser():
    root = argparse.ArgumentParser(description="Local speech for Omarchy. Bare text and stdin are accepted.")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("speak", "selection", "clipboard"):
        cmd = commands.add_parser(name)
        if name == "speak":
            cmd.add_argument("text", nargs="*")
        for flag in ("model", "voice", "voice-profile", "language", "description"):
            cmd.add_argument("--" + flag)
        for flag in ("rate", "pace"):
            cmd.add_argument("--" + flag, type=float)
        cmd.add_argument("--seed", type=int, default=42)
        cmd.add_argument("--detach", action="store_true")
        policies = cmd.add_mutually_exclusive_group()
        for policy in ("enqueue", "interrupt", "replace-all"):
            policies.add_argument("--" + policy, dest="policy", action="store_const", const=policy)
        cmd.set_defaults(policy="interrupt")
    commands.add_parser("daemon").add_argument("--http-port", type=int)
    commands.add_parser("ui").add_argument("--settings", action="store_true")
    for name in ("pause", "resume", "toggle", "stop", "clear", "history", "jobs", "doctor"):
        commands.add_parser(name)
    cmd = commands.add_parser("status")
    cmd.add_argument("--follow", action="store_true")
    cmd.add_argument("--bar", action="store_true")
    cmd = commands.add_parser("models")
    cmd.add_argument("--json", action="store_true")
    cmd = commands.add_parser("add-model")
    cmd.add_argument("id")
    cmd.add_argument("repository")
    cmd.add_argument("--base", required=True, help="Catalog ID with the same architecture and mode")
    cmd.add_argument("--revision", required=True, help="Full Hugging Face commit SHA")
    cmd.add_argument("--artifacts", required=True, help="JSON file mapping artifact paths to SHA-256 hashes")
    cmd = commands.add_parser("setup")
    cmd.add_argument("engine", choices=["kokoro", "qwen", "chatterbox", "omnivoice"])
    cmd.add_argument("--cuda", action="store_true")
    cmd = commands.add_parser("download")
    cmd.add_argument("model")
    for name in ("seek", "skip"):
        commands.add_parser(name).add_argument("seconds", type=float)
    commands.add_parser("rate").add_argument("rate", type=float)
    commands.add_parser("replay").add_argument("id")
    cmd = commands.add_parser("export")
    cmd.add_argument("id")
    cmd.add_argument("output")
    cmd = commands.add_parser("settings")
    cmd.add_argument("key", nargs="?", choices=["model", "rate", "pace", "idle_seconds", "device", "selection_shortcut", "clipboard_shortcut"])
    cmd.add_argument("value", nargs="?")
    cmd = commands.add_parser("voices")
    sub = cmd.add_subparsers(dest="action")
    add = sub.add_parser("add")
    add.add_argument("name")
    add.add_argument("sample")
    add.add_argument("--transcript", default="")
    add.add_argument("--transcribe", action="store_true", help="Use installed local Voxtype Whisper")
    return root


def main():
    os.umask(0o077)
    root = parser()
    argv = sys.argv[1:]
    names = next(a for a in root._actions if isinstance(a, argparse._SubParsersAction)).choices
    if not argv or (argv[0] not in names and argv[0] not in ("-h", "--help")):
        argv.insert(0, "speak")
    args = vars(root.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "daemon":
            from .service import main as daemon
            return daemon(args["http_port"])
        if command == "ui":
            from .ui import main as ui
            return ui(args["settings"])
        if command == "doctor":
            result = {"commands": {n: shutil.which(n) for n in ("mpv", "wl-paste", "ffmpeg", "voxtype", "pw-record")},
                      "data": str(data_dir()), "installedModels": [m["id"] for m in models() if installed(m)]}
            try:
                result["service"] = call("status")["state"]
            except RuntimeError as exc:
                result["service"] = str(exc)
        elif command == "models":
            result = [m | {"installed": installed(m)} for m in models()]
            if not args["json"]:
                for model in result:
                    print(f"{model['id']:38} {'installed' if model['installed'] else model['portStatus']:12} {model['repository'] or model['upstreamRepository']}")
                return
        elif command == "add-model":
            import re
            from .paths import config_dir, atomic_json, read_json
            if not re.fullmatch(r"[a-zA-Z0-9_-]+", args["id"]):
                raise ValueError("Use letters, digits, hyphens and underscores in the model ID")
            if any(m["id"] == args["id"] for m in models()):
                raise ValueError("Model ID already exists")
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args["repository"]):
                raise ValueError("Provide a Hugging Face owner/repository ID")
            if args["repository"].startswith("mlx-community/"):
                raise ValueError("MLX weights cannot run in the Linux engines")
            base = model_by_id(args["base"])
            if not base["engine"]:
                raise ValueError("Choose a base with a Linux adapter")
            result = base | {"id": args["id"], "displayName": args["id"], "repository": args["repository"],
                             "stability": "experimental", "portStatus": "community-unverified",
                             "revision": args["revision"],
                             "artifacts": json.loads(Path(args["artifacts"]).read_text())}
            from .artifacts import validate_model
            validate_model(result)
            path = config_dir() / "models.json"
            atomic_json(path, read_json(path, []) + [result])
        elif command == "setup":
            from .engines import setup
            setup(args["engine"], args["cuda"])
            return
        elif command == "download":
            from .engines import download
            result = download(model_by_id(args["model"]))
        elif command == "voices":
            from .voices import voices, add_voice
            result = add_voice(args["name"], args["sample"], args["transcript"], args["transcribe"]) if args["action"] == "add" else voices()
        elif command in ("speak", "selection", "clipboard"):
            detach = args.pop("detach")
            if command == "speak":
                text = " ".join(args.pop("text"))
                if not text and not sys.stdin.isatty():
                    text = sys.stdin.read(100_001)
            else:
                from .selection import read_selection
                text = read_selection(command == "clipboard")
            result = call("speak", text=text, **args)
            if not detach:
                identifier = result["id"]
                while True:
                    result = next(j for j in call("jobs") if j["id"] == identifier)
                    if result["state"] in ("complete", "failed", "cancelled"):
                        break
                    time.sleep(.3)
                if result["state"] == "failed":
                    raise RuntimeError(result["error"])
        elif command == "export":
            job = next((j for j in call("history") if j["id"] == args["id"]), None)
            if not job or not job.get("audio"):
                raise ValueError("History audio is unavailable")
            output = Path(args["output"]).expanduser()
            if output.exists():
                raise ValueError("Output already exists")
            if output.suffix.lower() == ".wav":
                shutil.copyfile(job["audio"], output)
            elif output.suffix.lower() in (".mp3", ".flac", ".ogg"):
                subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", job["audio"], str(output)], check=True)
            else:
                raise ValueError("Export as .wav, .mp3, .flac or .ogg")
            result = {"output": str(output)}
        elif command == "settings":
            if (args["key"] is None) != (args["value"] is None):
                raise ValueError("Provide both a setting name and value")
            values = {args["key"]: args["value"]} if args["key"] else {}
            result = call("settings", values=values)
        elif command == "status":
            while True:
                result = call("status")
                if args["bar"]:
                    result = {"text": "󰕾", "alt": result["state"], "class": result["state"],
                              "tooltip": f"SayIt: {result['state']}"}
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if not args["follow"]:
                    return
                time.sleep(.5)
        else:
            result = call(command, **args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        if command in ("speak", "selection", "clipboard"):
            call("stop")
        raise SystemExit(130)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"sayit: {exc}", file=sys.stderr)
        if command in ("selection", "clipboard") and shutil.which("notify-send"):
            subprocess.run(["notify-send", "--app-name=SayIt", "--", "SayIt", str(exc)], check=False)
        raise SystemExit(1)
