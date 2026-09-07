# Port status

Only the hash-locked Kokoro CPU runtime is enabled. Full feature and model parity is not complete. Experimental adapters are retained in Git history and must not be re-enabled without locks and offline runtime tests.

The reference is SayIt commit `fbf019a81f3b40788d117314188a65a5cffa7cb6`. Its complete catalog is preserved in `data/upstream-models.json`. Apple MLX checkpoints cannot run unchanged in the Linux PyTorch runtimes. Mapping a family to its original Linux weights preserves its architecture, but not necessarily its quantization, memory footprint or exact audio output.

## Model inventory

| Upstream entry | Linux implementation | Validation |
| --- | --- | --- |
| Kokoro BF16 | hexgrad/Kokoro-82M, original PyTorch weights | Real English and Spanish offline synthesis passed on CPU |
| Qwen3 0.6B Base 8-bit | Qwen/Qwen3-TTS-12Hz-0.6B-Base | Disabled pending source locks and runtime validation |
| Qwen3 1.7B VoiceDesign 8-bit | Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign | Disabled pending source locks and runtime validation |
| Qwen3 1.7B CustomVoice 8-bit | Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice | Disabled pending source locks and runtime validation |
| Chatterbox Turbo FP16 | ResembleAI/chatterbox-turbo | Disabled pending source locks and runtime validation |
| Chatterbox multilingual v3 FP16 | ResembleAI/chatterbox, v3 checkpoint | Disabled pending source locks and runtime validation |
| Chatterbox FP16 | ResembleAI/chatterbox, original checkpoint | Disabled pending source locks and runtime validation |
| OmniVoice | k2-fsa/OmniVoice | Disabled pending source locks and runtime validation |
| Kitten Mini 0.8 | Not ported | Upstream experimental |
| Kitten Nano 0.8 4-bit | Not ported | Upstream experimental |
| Pocket TTS | Not ported | Upstream experimental |
| Soprano 1.1 | Not ported | Upstream experimental |
| Irodori v3 VoiceDesign | Not ported | Upstream experimental |
| Vyvo English 4-bit | Not ported | Upstream experimental |
| Orpheus 3B BF16 | Not ported | Upstream experimental |
| Orpheus 3B 4-bit | Not ported | Upstream experimental |
| Fish Audio S2 Pro | Not ported | Already unavailable upstream |
| MOSS TTS | Not ported | Already unavailable upstream |
| Marvis 250M | Not ported | Already unavailable upstream |
| IndexTTS | Not ported | Already unavailable upstream |
| Echo | Not ported | Already unavailable upstream |
| MOSS Nano | Not ported | Already unavailable upstream |

## Feature coverage

| Feature | Status |
| --- | --- |
| Explicit selection and separate clipboard action | Implemented via wl-paste; primary-selection availability depends on the app |
| Configurable global shortcuts | Native Hyprland Lua bindings |
| Player and tray | Native Quickshell bar popup plus GTK3 management window and optional Ayatana indicator; live popup layout and window smoke checks passed |
| Pause, resume, seek, skip, speed | Implemented with mpv; MPRIS pause/resume tested with real audio |
| Follow spoken text | Chunk-level display; exact word timing not implemented |
| Progressive audio | Text chunks enter the mpv playlist as synthesis completes; real progressive playback and cross-chunk seek tested; no model-level token streaming |
| History, replay and export | Implemented; automated lifecycle and audio concatenation tests |
| Queue policies and cancellation | Implemented; cancellation, queue and stale-audio regression tests |
| One resident TTS worker and idle unload | Implemented and tested; online download validation can temporarily load a separate model |
| Model downloads | Explicit install/download commands and UI; load validation before ready marker |
| Community repositories | Compatible base-adapter registration; no automatic architecture discovery |
| Model download progress/cancel/remove | Log progress only; full management UI not implemented |
| Built-in voices | Catalog presets exposed; only Kokoro voices tested |
| Voice design | Disabled pending locked and tested engines |
| Cloning | Profile management implemented; clone synthesis disabled |
| Random voice discovery | Not implemented |
| Profile editing, reordering, deletion | Not implemented |
| Local-only inference | Hash-verified Kokoro artifacts, offline flags and download guard; English/Spanish confirmed; Japanese/Chinese disabled |
| Agent narration | CLI with detached/enqueued submissions; no installed agent skill |
| REST API | Optional authenticated loopback API; auth and request tests; upstream wire compatibility not implemented |
| Startup | systemd user unit and desktop entry |
| macOS Services menu | No Linux-wide equivalent; use shortcut, launcher or CLI |
| Automatic retention and diagnostics export | Not implemented |

## Next acceptance work

Restore the Qwen, Chatterbox and OmniVoice adapters only after committing complete hashed dependency locks and pinned hashes for all primary and auxiliary model artifacts, then test actual weights on CPU and a supported GPU. Verify every exposed language, voice mode, cloning requirement and offline dependency. Their generated WAVs, timing and memory use are required evidence before marking them supported.

Port the eight experimental catalog entries next, keeping upstream-unavailable entries visible but disabled. Finish random voice discovery, profile/model management and word timing, then test long-form playback and selection capture across the main Omarchy applications. Full parity should not be claimed until these checks pass.
