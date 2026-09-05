"""GTK desktop player. Inference and downloads never run on the GTK thread."""
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
from .catalog import models, installed
from .paths import data_dir
from .service import call


class Window(Gtk.Window):
    def __init__(self):
        super().__init__(title="SayIt")
        self.set_default_size(740, 650)
        self.set_border_width(18)
        self.recording = None
        self.sample_path = None
        self.status_busy = False
        self.connect("destroy", self.close)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.add(outer)
        title = Gtk.Label(label="SayIt · Local speech", xalign=0)
        title.get_style_context().add_class("title")
        outer.pack_start(title, False, False, 0)
        self.message = Gtk.Label(label="Select a model to get started", xalign=0, wrap=True, selectable=True)
        outer.pack_start(self.message, False, False, 0)
        book = Gtk.Notebook()
        outer.pack_start(book, True, True, 0)
        for label, build in (("Player", self.player_page), ("Models", self.models_page),
                             ("Voice studio", self.voices_page), ("History", self.history_page),
                             ("Settings", self.settings_page)):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            box.set_border_width(12)
            build(box)
            book.append_page(box, Gtk.Label(label=label))
        self.show_all()
        self.poll_id = GLib.timeout_add(500, self.poll)

    def close(self, *_):
        if self.recording:
            self.recording.send_signal(signal.SIGINT)
            self.recording.wait(timeout=3)
        if self.sample_path:
            Path(self.sample_path).unlink(missing_ok=True)
        Gtk.main_quit()

    def task(self, fn, done=None):
        def run():
            try:
                result = fn()
                GLib.idle_add(finish, result, None)
            except Exception as exc:
                GLib.idle_add(finish, None, str(exc))
        def finish(result, error):
            if error:
                self.message.set_text(error)
            elif done:
                done(result)
            return False
        threading.Thread(target=run, daemon=True).start()

    def button(self, box, label, fn):
        button = Gtk.Button(label=label)
        button.connect("clicked", lambda *_: fn())
        box.pack_start(button, False, False, 0)
        return button

    def entry(self, box, placeholder):
        entry = Gtk.Entry(placeholder_text=placeholder)
        box.pack_start(entry, False, False, 0)
        return entry

    def textview(self, box, editable=True):
        view = Gtk.TextView(editable=editable, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(100)
        scroll.add(view)
        box.pack_start(scroll, True, True, 0)
        return view.get_buffer()

    def player_page(self, box):
        self.model = Gtk.ComboBoxText()
        for model in models():
            if model["engine"]:
                self.model.append(model["id"], f"{model['displayName']} · {model['id']}")
        self.model.set_active(0)
        box.pack_start(self.model, False, False, 0)
        self.voice = Gtk.ComboBoxText()
        box.pack_start(self.voice, False, False, 0)
        self.language = self.entry(box, "Language code, for example en, es, ja")
        self.description = self.entry(box, "Voice description, for models with voice design")
        self.profile = self.entry(box, "Saved voice name or ID, optional")
        self.text = self.textview(box)
        self.text.set_text("Select text in another app and use the SayIt shortcut, or paste text here.")
        self.now = Gtk.Label(xalign=0, wrap=True, selectable=True)
        box.pack_start(self.now, False, False, 0)
        self.seek = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, .1)
        self.seek.set_draw_value(False)
        self.seek.connect("change-value", self.seek_changed)
        box.pack_start(self.seek, False, False, 0)
        row = Gtk.Box(spacing=6)
        box.pack_start(row, False, False, 0)
        self.button(row, "Read", self.speak)
        self.button(row, "Read clipboard", self.clipboard)
        self.button(row, "Pause / resume", lambda: self.task(lambda: call("toggle")))
        self.button(row, "Stop", lambda: self.task(lambda: call("stop")))
        self.rate = Gtk.SpinButton.new_with_range(.5, 2, .1)
        self.rate.set_value(1)
        self.rate.set_tooltip_text("Playback speed")
        self.rate.connect("value-changed", lambda w: self.task(lambda: call("rate", rate=w.get_value())))
        row.pack_start(self.rate, False, False, 0)
        self.model.connect("changed", self.model_changed)
        self.model_changed()

    def model_changed(self, *_):
        model = next(m for m in models() if m["id"] == self.model.get_active_id())
        self.voice.remove_all()
        for voice in model["voices"]:
            self.voice.append_text(voice)
        self.voice.set_active(0)
        self.language.set_text(model.get("defaultLanguage") or "en")
        self.description.set_sensitive(model["capabilities"].get("voiceDescription", False))
        self.profile.set_sensitive(model["capabilities"].get("voiceCloning", False))

    def speak(self):
        text = self.text.get_text(*self.text.get_bounds(), True)
        options = {"model": self.model.get_active_id(), "language": self.language.get_text() or None,
                   "rate": self.rate.get_value()}
        if self.profile.get_sensitive() and self.profile.get_text():
            options["voice_profile"] = self.profile.get_text()
        elif self.voice.get_active_text():
            options["voice"] = self.voice.get_active_text()
        if self.description.get_sensitive() and self.description.get_text():
            options["description"] = self.description.get_text()
        self.task(lambda: call("speak", text=text, **options), lambda _: self.message.set_text("Speech queued"))

    def clipboard(self):
        from .selection import read_selection
        def done(text):
            self.text.set_text(text)
            self.speak()
        self.task(lambda: read_selection(True), done)

    def seek_changed(self, widget, scroll, value):
        self.task(lambda: call("seek", seconds=value))
        return False

    def models_page(self, box):
        box.pack_start(Gtk.Label(label="Linux weights for the same model families. MLX quantizations are not interchangeable.\nInstall an engine once, then download its model. Downloads may be several GB.", wrap=True, xalign=0), False, False, 0)
        self.model_list = Gtk.ComboBoxText()
        for model in models():
            self.model_list.append(model["id"], f"{model['id']} · {model['portStatus']}")
        self.model_list.set_active(0)
        box.pack_start(self.model_list, False, False, 0)
        def selected():
            return next(m for m in models() if m["id"] == self.model_list.get_active_id())
        def install_engine():
            from .engines import setup
            model = selected()
            self.message.set_text("Installing engine; progress is in the launching terminal")
            self.task(lambda: setup(model["engine"]), lambda _: self.message.set_text("Engine installed"))
        def download_model():
            from .engines import download
            model = selected()
            self.message.set_text("Downloading and checking model; see ~/.local/share/sayit/engine.log")
            self.task(lambda: download(model), lambda _: self.message.set_text("Model ready"))
        self.button(box, "Install engine for CPU", install_engine)
        self.button(box, "Download model", download_model)
        self.button(box, "Open model card", lambda: Gtk.show_uri_on_window(self,
                    "https://huggingface.co/" + (selected()["repository"] or selected()["upstreamRepository"]), 0))
        box.pack_start(Gtk.Label(label="Entries marked not-ported are inventory only. See docs/parity.md for the remaining work.", wrap=True, xalign=0), False, False, 0)

    def voices_page(self, box):
        box.pack_start(Gtk.Label(label="Record or import a clean sample of 6 to 10 seconds.\nUse a voice you have permission to clone. Samples stay on this computer.", wrap=True, xalign=0), False, False, 0)
        self.voice_name = self.entry(box, "Voice name")
        self.sample = self.entry(box, "Path to a reference audio file")
        self.transcript = self.entry(box, "Exact words spoken in the sample")
        self.auto_transcribe = Gtk.CheckButton(label="Transcribe sample with local Voxtype / Whisper")
        box.pack_start(self.auto_transcribe, False, False, 0)
        self.record_button = self.button(box, "Record sample", self.record)
        def save():
            from .voices import add_voice
            name, sample, text, auto = self.voice_name.get_text(), self.sample.get_text(), self.transcript.get_text(), self.auto_transcribe.get_active()
            self.task(lambda: add_voice(name, sample, text, auto), lambda v: (
                self.message.set_text(f"Saved {v['name']}. " + " ".join(v["warnings"])), self.refresh_voices()))
        self.button(box, "Save voice", save)
        self.saved_voices = self.textview(box, False)
        self.refresh_voices()

    def refresh_voices(self):
        from .voices import voices
        self.saved_voices.set_text("\n\n".join(f"{v['name']} · {v['duration']:.1f}s\n{v['transcript']}" for v in voices()))

    def record(self):
        if self.recording:
            self.recording.send_signal(signal.SIGINT)
            self.recording.wait(timeout=3)
            self.recording = None
            self.record_button.set_label("Record sample")
            self.sample.set_text(self.sample_path)
            return
        if self.sample_path:
            Path(self.sample_path).unlink(missing_ok=True)
        import os
        fd, self.sample_path = tempfile.mkstemp(suffix=".wav", dir=data_dir())
        os.close(fd)
        try:
            self.recording = subprocess.Popen(["pw-record", "--rate", "24000", "--channels", "1", self.sample_path],
                                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            self.message.set_text(str(exc))
            return
        self.record_button.set_label("Stop recording")
        process = self.recording
        def stop():
            if self.recording is process:
                self.record()
            return False
        GLib.timeout_add_seconds(30, stop)

    def history_page(self, box):
        self.history_choice = Gtk.ComboBoxText()
        box.pack_start(self.history_choice, False, False, 0)
        self.history_text = self.textview(box, False)
        def refresh():
            def done(jobs):
                self.history_choice.remove_all()
                for job in jobs:
                    self.history_choice.append(job["id"], f"{job['state']} · {job['text'][:65]}")
                self.history_choice.set_active(0)
                self.history_text.set_text("\n\n".join(f"{j['id']}\n{j['text']}\n{j.get('error') or j['state']}" for j in jobs))
            self.task(lambda: call("history"), done)
        self.button(box, "Refresh history", refresh)
        self.button(box, "Replay selected", lambda: self.task(lambda: call("replay", id=self.history_choice.get_active_id())))
        self.button(box, "Open audio folder", lambda: Gtk.show_uri_on_window(self, (data_dir() / "audio").as_uri(), 0))
        refresh()

    def settings_page(self, box):
        self.default_model = self.entry(box, "Default model ID")
        self.idle = Gtk.SpinButton.new_with_range(0, 86400, 60)
        self.idle.set_value(600)
        box.pack_start(Gtk.Label(label="Unload model after idle seconds", xalign=0), False, False, 0)
        box.pack_start(self.idle, False, False, 0)
        self.device = Gtk.ComboBoxText()
        for value in ("auto", "cpu", "cuda"):
            self.device.append_text(value)
        self.device.set_active(0)
        box.pack_start(self.device, False, False, 0)
        def save():
            values = {"model": self.default_model.get_text(), "idle_seconds": self.idle.get_value(),
                      "device": self.device.get_active_text()}
            self.task(lambda: call("settings", values=values), lambda _: self.message.set_text("Settings saved"))
        self.button(box, "Save settings", save)
        def loaded(settings):
            self.default_model.set_text(settings["model"])
            self.idle.set_value(settings["idle_seconds"])
            self.device.set_active(("auto", "cpu", "cuda").index(settings["device"]))
            self.model.set_active_id(settings["model"])
        self.task(lambda: call("settings"), loaded)
        box.pack_start(Gtk.Label(label="F9 keeps its Voxtype dictation binding. SayIt exposes media controls so Voxtype can pause speech during recording.\n\nSuggested speech shortcuts are in integration/bindings.lua.", wrap=True, xalign=0), False, False, 0)

    def poll(self):
        if self.status_busy:
            return True
        self.status_busy = True
        def poll():
            try:
                snapshot = call("status")
                GLib.idle_add(update, snapshot)
            except Exception:
                GLib.idle_add(update, None)
        def update(snapshot):
            self.status_busy = False
            if snapshot:
                self.seek.set_range(0, max(1, snapshot["duration"]))
                self.seek.set_value(snapshot["position"])
                job = snapshot["current"]
                current_text = ""
                if job:
                    current_text = next((s["text"] for s in job["segments"]
                                         if s["start"] <= snapshot["position"] < s["start"] + s["duration"]), "")
                    if job["state"] == "failed":
                        self.message.set_text(job["error"])
                self.now.set_text(f"{snapshot['state']} · {snapshot['position']:.0f} / {snapshot['duration']:.0f}s\n{current_text}")
            return False
        threading.Thread(target=poll, daemon=True).start()
        return True


def main():
    window = Window()
    try:
        gi.require_version("AyatanaAppIndicator3", "0.1")
        from gi.repository import AyatanaAppIndicator3
        indicator = AyatanaAppIndicator3.Indicator.new("omarchy-sayit", "audio-volume-high-symbolic",
                                                     AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS)
        indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
        menu = Gtk.Menu()
        for label, fn in (("Show player", window.present), ("Pause / resume", lambda: window.task(lambda: call("toggle"))),
                          ("Stop", lambda: window.task(lambda: call("stop"))), ("Quit player", window.destroy)):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _, fn=fn: fn())
            menu.append(item)
        menu.show_all()
        indicator.set_menu(menu)
        window.connect("delete-event", lambda *_: (window.hide(), True)[1])
    except (ValueError, ImportError):
        pass
    Gtk.main()

