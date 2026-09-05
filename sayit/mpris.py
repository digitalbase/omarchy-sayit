"""Desktop media controls, including Voxtype's existing pause/resume integration."""
import signal
import subprocess
import sys

XML = '''<node>
<interface name="org.mpris.MediaPlayer2">
 <method name="Raise"/><method name="Quit"/>
 <property name="CanQuit" type="b" access="read"/>
 <property name="CanRaise" type="b" access="read"/>
 <property name="HasTrackList" type="b" access="read"/>
 <property name="Identity" type="s" access="read"/>
 <property name="DesktopEntry" type="s" access="read"/>
 <property name="SupportedUriSchemes" type="as" access="read"/>
 <property name="SupportedMimeTypes" type="as" access="read"/>
</interface>
<interface name="org.mpris.MediaPlayer2.Player">
 <method name="Play"/><method name="Pause"/><method name="PlayPause"/><method name="Stop"/>
 <method name="Next"/><method name="Previous"/>
 <method name="Seek"><arg type="x" direction="in"/></method>
 <method name="SetPosition"><arg type="o" direction="in"/><arg type="x" direction="in"/></method>
 <signal name="Seeked"><arg type="x"/></signal>
 <property name="PlaybackStatus" type="s" access="read"/>
 <property name="Metadata" type="a{sv}" access="read"/>
 <property name="Rate" type="d" access="readwrite"/>
 <property name="Volume" type="d" access="readwrite"/>
 <property name="Position" type="x" access="read"/>
 <property name="MinimumRate" type="d" access="read"/>
 <property name="MaximumRate" type="d" access="read"/>
 <property name="CanGoNext" type="b" access="read"/>
 <property name="CanGoPrevious" type="b" access="read"/>
 <property name="CanPlay" type="b" access="read"/>
 <property name="CanPause" type="b" access="read"/>
 <property name="CanSeek" type="b" access="read"/>
 <property name="CanControl" type="b" access="read"/>
</interface></node>'''


def run(service):
    from gi.repository import Gio, GLib
    loop = GLib.MainLoop()
    path = "/org/mpris/MediaPlayer2"
    interface = "org.mpris.MediaPlayer2.Player"
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def properties():
        snapshot = service.snapshot()
        job = snapshot["current"]
        metadata = {}
        if job:
            metadata = {"mpris:trackid": GLib.Variant("o", f"/org/mpris/MediaPlayer2/track/{job['id']}"),
                        "mpris:length": GLib.Variant("x", int(job.get("duration", 0) * 1e6)),
                        "xesam:title": GLib.Variant("s", "SayIt reading"),
                        "xesam:artist": GLib.Variant("as", ["SayIt"])}
        state = snapshot["state"]
        return {"PlaybackStatus": GLib.Variant("s", "Paused" if state == "paused" else
                                               "Playing" if state == "playing" else "Stopped"),
                "Metadata": GLib.Variant("a{sv}", metadata), "Rate": GLib.Variant("d", float(snapshot["rate"])),
                "Volume": GLib.Variant("d", (service.player.get("volume", 100) or 0) / 100),
                "Position": GLib.Variant("x", int(snapshot["position"] * 1e6)),
                "MinimumRate": GLib.Variant("d", .5), "MaximumRate": GLib.Variant("d", 2.),
                **{key: GLib.Variant("b", value) for key, value in {
                    "CanGoNext": False, "CanGoPrevious": False, "CanPlay": bool(job),
                    "CanPause": state in ("playing", "paused"), "CanSeek": state in ("playing", "paused"),
                    "CanControl": True}.items()}}

    root = {"Identity": GLib.Variant("s", "SayIt"), "DesktopEntry": GLib.Variant("s", "omarchy-sayit"),
            "CanQuit": GLib.Variant("b", True), "CanRaise": GLib.Variant("b", True),
            "HasTrackList": GLib.Variant("b", False), "SupportedUriSchemes": GLib.Variant("as", []),
            "SupportedMimeTypes": GLib.Variant("as", [])}

    def method(conn, sender, obj, iface, name, params, invocation):
        try:
            if name == "Quit":
                loop.quit()
            elif name == "Raise":
                subprocess.Popen([sys.executable, "-m", "sayit", "ui"])
            elif name in ("Play", "PlayPause"):
                snapshot = service.snapshot()
                job = snapshot["current"]
                if job and snapshot["state"] in ("complete", "cancelled", "failed") and job.get("audio"):
                    service.dispatch({"command": "replay", "id": job["id"]})
                else:
                    service.dispatch({"command": "resume" if name == "Play" else "toggle"})
            elif name in ("Pause", "Stop"):
                service.dispatch({"command": name.lower()})
            elif name in ("Seek", "SetPosition"):
                args = params.unpack()
                current = properties()
                valid = name == "Seek" or (
                    current["Metadata"].unpack().get("mpris:trackid") == args[0] and
                    0 <= args[1] <= current["Metadata"].unpack().get("mpris:length", 0))
                if valid:
                    service.dispatch({"command": "skip" if name == "Seek" else "seek", "seconds": args[-1] / 1e6})
                    conn.emit_signal(None, path, interface, "Seeked", GLib.Variant("(x)",
                                     (int(service.snapshot()["position"] * 1e6),)))
            invocation.return_value(None)
        except Exception as exc:
            invocation.return_dbus_error("org.mpris.MediaPlayer2.Error.Failed", str(exc))

    def get_prop(conn, sender, obj, iface, name):
        return (properties() if iface == interface else root).get(name)

    def set_prop(conn, sender, obj, iface, name, value):
        try:
            if name == "Rate":
                if value.unpack() == 0:
                    service.dispatch({"command": "pause"})
                else:
                    service.dispatch({"command": "rate", "rate": value.unpack()})
            elif name == "Volume":
                service.player.command("set_property", "volume", max(0, min(100, value.unpack() * 100)))
            else:
                return False
            return True
        except Exception:
            return False

    info = Gio.DBusNodeInfo.new_for_xml(XML)
    registrations = [connection.register_object(path, iface, method, get_prop, set_prop) for iface in info.interfaces]
    owner = Gio.bus_own_name_on_connection(connection, "org.mpris.MediaPlayer2.sayit", Gio.BusNameOwnerFlags.NONE, None, None)
    previous = {}

    def update():
        current = properties()
        changed = {k: v for k, v in current.items() if k != "Position" and previous.get(k) != v}
        if changed:
            connection.emit_signal(None, path, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                   GLib.Variant("(sa{sv}as)", (interface, changed, [])))
        previous.update(current)
        return True

    GLib.timeout_add(500, update)
    for sig in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        Gio.bus_unown_name(owner)
        for registration in registrations:
            connection.unregister_object(registration)

