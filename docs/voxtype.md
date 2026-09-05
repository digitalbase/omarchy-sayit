# Reusing Omarchy's F9 dictation

Inspected on the development machine, 2026-09-05. Voxtype package version: `1.0.1-1`.

## What F9 does

`/usr/share/omarchy/default/hypr/bindings/voxtype.lua` binds press to `voxtype record start` and release to `voxtype record stop`. Super+Ctrl+X calls `voxtype record toggle`. The built-in Voxtype keyboard listener is disabled; Hyprland owns the shortcuts.

The user service runs `/usr/bin/voxtype daemon`. This machine's configuration uses local Whisper `base.en`, English, the default microphone and a 60-second recording limit. It pastes through Shift+Insert. `audio.pause_media = true` is already enabled.

Voxtype converts speech to text. SayIt converts text to speech. Whisper weights cannot replace a TTS model, and Voxtype's Vulkan acceleration does not automatically accelerate PyTorch TTS models.

## Reuse implemented

1. **MPRIS playback controls.** SayIt publishes `org.mpris.MediaPlayer2.sayit`. Voxtype enumerates MPRIS players, pauses those whose PlaybackStatus is Playing, remembers their bus names and calls Play when recording finishes. No custom F9 wrapper or Voxtype configuration change is needed. SayIt also reads Voxtype's activity flag before starting a generated chunk, covering the case where recording begins before audio is ready. Omarchy's existing media controls can use the same player.
2. **Local sample transcription.** Voice import normalizes audio using FFmpeg and calls Voxtype's file-transcription command. This reuses the installed local Whisper model. It explicitly selects local Whisper even if a different remote engine is configured. The command does not type or paste the result.
3. **Desktop conventions.** SayIt follows the same user-service lifecycle and compositor-managed shortcut pattern. Its status command emits line-delimited JSON that a bar widget can consume.

The existing indicator in `/usr/share/omarchy/shell/plugins/bar/indicators/Dictation.qml` consumes `omarchy-voxtype-status`, which wraps `voxtype status --follow --extended --format json`. A future combined voice widget can consume both status streams. The dedicated `digitalbase.sayit` bar popup now consumes SayIt status and playback commands. It leaves the dictation indicator in place. No packaged Omarchy files were modified.

## What should stay separate

- The F9 dictation workflow and output preferences belong to Voxtype.
- TTS model download, synthesis, playback and history belong to SayIt.
- Voice Studio records samples explicitly through PipeWire, rather than intercepting everyday dictation or retaining microphone recordings behind the user's back.
- Automatic sample transcription may briefly load another Whisper instance. Voxtype's file command is a separate process; it is not an API into the already-loaded daemon model.

## Validation

The installed F9 bindings were checked with `hyprctl -j binds`. SayIt's MPRIS Pause/Play calls were tested during real Kokoro playback: Pause froze playback position and Play resumed it. This verifies the interface Voxtype uses; it does not constitute a live F9 microphone test.

The installed `voxtype transcribe` command successfully transcribed a generated 16 kHz sample. It misheard "Omarchy" as "Amarky", so sample transcripts need review. No live microphone recording was made during validation.

The added F10 bindings passed `hyprctl reload` and `hyprctl configerrors`. The previous user bindings were backed up as `~/.config/hypr/bindings.lua.bak-sayit-20260905`.

Sources: [Voxtype](https://github.com/peteonrails/voxtype), [MPRIS player specification](https://specifications.freedesktop.org/mpris/latest/Player_Interface.html), and the installed Omarchy files listed above.
