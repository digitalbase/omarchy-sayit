# SayIt for Omarchy

A native Linux port in progress of [callebtc/sayit](https://github.com/callebtc/sayit). Select text, press F10, and hear a local speech model read it aloud. F9 remains Omarchy's Voxtype dictation shortcut.

**This is an early working port, not full upstream parity.** Kokoro has been tested with real offline English and Spanish synthesis on Omarchy. Qwen3-TTS, Chatterbox and OmniVoice have Linux adapters that still need model-by-model runtime validation. The catalog retains all 22 upstream entries, including models that have not been ported. See [the parity tracker](docs/parity.md).

## What works

- Explicit Wayland selection or clipboard reading, without clipboard monitoring.
- GTK player and optional tray menu, pause/resume, stop, seek and 0.5–2× playback speed.
- Speech starts after the first text chunk; subsequent chunks play as they become ready. The player displays the current chunk of text.
- A per-user service, CLI, queue policies, saved audio history, replay and audio export.
- One resident synthesis worker, model switching and configurable idle unloading.
- Voice sample recording/import, duration/silence/clipping checks, saved profiles and optional transcription using the installed local Voxtype Whisper model.
- MPRIS controls for media keys, Omarchy's media UI and Voxtype's pause-during-recording behavior.
- An optional token-protected loopback HTTP API. It is disabled by default.

## Install on Omarchy

The desktop app uses system Python and GTK through PyGObject. Inference engines use separate Python 3.11 environments, since their PyTorch and Transformers dependencies conflict.

Install missing system dependencies with Omarchy's package command:

```sh
omarchy pkg add python python-gobject gtk3 mpv wl-clipboard ffmpeg
```

Omarchy normally includes PipeWire's `pw-record` for recording. `libayatana-appindicator` adds the optional tray menu. Voxtype is optional and only needed for automatic reference transcription and dictation integration.

From this checkout:

```sh
./scripts/bootstrap.sh
./bin/sayit setup kokoro
./bin/sayit download kokoro-bf16
./scripts/install.sh
sayit ui
```

The installer links this checkout into `~/.local/bin`, installs a desktop launcher and enables a user service. Keep the checkout in place. Open Config in the bar popup and save Settings to apply the selection and clipboard shortcuts. Selection defaults to F10; clipboard defaults to unassigned. Settings checks conflicts, backs up the user bindings, reloads Hyprland and restores the old file if validation fails. Optional playback shortcuts are in [integration/bindings.lua](integration/bindings.lua).

| Shortcut | Action |
| --- | --- |
| F9, existing Omarchy binding | Hold to dictate with Voxtype |
| F10 | Read selected text |
| Unassigned by default | Read clipboard; configurable in Settings |
| Ctrl+F10 | Pause/resume |
| Alt+F10 | Stop and clear the queue |
| Super+F10 | Open the player |

Some Wayland apps do not publish a primary selection. In those apps, copy the text and click Read clipboard, or assign a clipboard shortcut in Settings. There is no universal Linux equivalent of macOS Accessibility selection retrieval.

## Omarchy bar player

Install the native Quickshell bar popup with:

```sh
./scripts/install-bar.sh
```

SayIt's original speaking-profile icon sits in the center section of the bar. The compact popup has selection/clipboard reading and play buttons beside four recent readings. A playing reading's button pauses or resumes it. Right-clicking the bar icon also toggles playback. The left-aligned top buttons are Read clipboard, Read selection and Config. Reading buttons show the configured keyboard shortcuts. The bar icon pulses in the accent color during generation and remains steady during playback. Config opens Settings directly, including the two shortcut fields; models, voices and the full player are available in the other tabs. The header uses Omarchy's PanelHero component, and reading rows use the same typography and outward hover margins as Obsidian Daily. The icon comes from upstream SayIt under its MIT license; see the bundled icon notice.

The installer backs up your bar configuration and installs `digitalbase.sayit` under the user plugin directory. No packaged Omarchy files are changed. Disable it with `omarchy plugin disable digitalbase.sayit`.

## CLI

```sh
sayit "Read this aloud"
printf 'Read from stdin' | sayit
sayit selection --detach
sayit clipboard --detach
sayit speak "Read this next" --enqueue --detach
sayit pause
sayit resume
sayit seek 10
sayit skip -5
sayit rate 1.3
sayit stop
sayit history
sayit replay JOB_ID
sayit export JOB_ID speech.mp3
sayit status --follow
sayit status --follow --bar
sayit doctor
```

The default queue policy interrupts the current job and preserves pending jobs. `--enqueue` appends; `--replace-all` cancels current and pending jobs. `--detach` returns the accepted job immediately, which also supports spoken coding-agent updates.

```sh
sayit settings model kokoro-bf16
sayit settings idle_seconds 600
sayit settings device cpu
sayit settings selection_shortcut F10
sayit settings clipboard_shortcut "CTRL + ALT + R"
sayit settings clipboard_shortcut ""  # Unassign
sayit models
sayit setup qwen
sayit download qwen3-17b-customvoice-8bit
sayit speak "Hello" --model qwen3-17b-customvoice-8bit --voice vivian
```

Use `setup ENGINE --cuda` for NVIDIA PyTorch wheels. CPU is the default installation. AMD GPU acceleration has not been validated. Existing model IDs retain upstream names for traceability: `8bit` or `bf16` in an ID describes the upstream entry, **not the Linux runtime precision**. Linux uses original PyTorch weights, with float32 on CPU and model-dependent GPU precision.

Compatible community repositories can reuse an adapter:

```sh
sayit add-model my-model owner/repository --base qwen3-17b-customvoice-8bit
sayit download my-model
```

The repository must have the same architecture, file layout and synthesis mode as its base. This does not support arbitrary Hugging Face models or MLX conversions. Community repositories inherit the base's voice/language metadata; review and update `~/.config/sayit/models.json` if needed. Review the actual repository's model license before downloading.

## Voice studio and Voxtype

Record a sample in Voice studio or import an existing audio file. Use a clean 6–10 second recording and the exact words spoken. Different models impose different duration limits. Use a voice you have permission to clone.

```sh
sayit voices add "My voice" reference.wav --transcript "The words I said."
sayit voices add "My voice" reference.wav --transcribe
sayit speak "Hello again" --model qwen3-06b-base-8bit --voice-profile "My voice"
```

`--transcribe` converts the sample to 16 kHz mono and invokes `voxtype --engine whisper --whisper-mode local transcribe`. It reuses the installed Whisper model, reads no clipboard and pastes nothing. Review the transcript before using it. Automatic transcription can mishear names.

Your Voxtype setting `audio.pause_media = true` makes F9 pause actively playing MPRIS players, including SayIt, and resume them afterwards. SayIt uses the standard protocol; it does not replace or rebind Voxtype. See [the integration findings](docs/voxtype.md).

## Local API

Stop the installed service before running a foreground instance:

```sh
systemctl --user stop sayit.service
sayit daemon --http-port 8765
```

The API binds only `127.0.0.1`. Every route requires `Authorization: Bearer TOKEN`; the token is in `~/.config/sayit/api-token` with mode 0600. No CORS access is enabled.

| Method and route | Body or result |
| --- | --- |
| `GET /v1/status` | Playback state |
| `GET /v1/models` | Catalog and installed status |
| `GET /v1/voices` | Saved profiles |
| `GET /v1/history`, `GET /v1/jobs` | Jobs and audio paths |
| `POST /v1/speech` | `{"text":"Hello", "model":"kokoro-bf16", "policy":"enqueue"}` |
| `POST /v1/playback` | `{"command":"pause"}` or other playback commands |

This API is not wire-compatible with upstream SayIt's REST API. Stop the foreground instance and run `systemctl --user start sayit.service` to return to the normal desktop service.

## Storage and privacy

`~/.config/sayit` holds settings and the optional API token. `~/.local/share/sayit` holds engine environments, downloaded models, voice samples, history, audio and engine logs. `$XDG_RUNTIME_DIR/sayit` holds private sockets. Standard XDG overrides are supported.

Downloads and engine installation use the network. Synthesis workers set Hugging Face and Transformers offline mode. Some language frontends may need a separate initial dictionary download; only Kokoro English and Spanish have been verified offline. Engine packages and community models are third-party software.

History intentionally retains text and audio. There is no automatic retention limit yet. MPRIS metadata uses a generic title instead of exposing spoken text to other media widgets. The service does not collect analytics or monitor clipboard contents.

## Development and removal

```sh
python -m unittest discover -s tests -v
python -m compileall -q sayit
journalctl --user -u sayit.service
```

To remove the app, disable `sayit.service`, remove its unit, the `~/.local/bin/sayit` symlink and `~/.local/share/applications/omarchy-sayit.desktop`, then remove any bindings you added. Your models and recordings remain in the XDG data directory until you choose to delete them.

The upstream MIT notice is retained in [LICENSE](LICENSE). Model licenses are separate. Upstream catalog snapshot: `callebtc/sayit@fbf019a81f3b40788d117314188a65a5cffa7cb6`.
