"""Optional loopback API. Desktop IPC remains a private Unix socket."""
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import secrets
import threading
from .paths import config_dir
from .service import MAX_REQUEST


def token():
    path = config_dir() / "api-token"
    try:
        with path.open("x") as stream:
            path.chmod(0o600)
            stream.write(secrets.token_urlsafe(32))
    except FileExistsError:
        pass
    return path.read_text().strip()


def start(service, port):
    secret = token()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + secret):
                self.reply(401, {"error": "Bearer token required"})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            commands = {"/v1/status": "status", "/v1/models": "models", "/v1/voices": "voices", "/v1/history": "history", "/v1/jobs": "jobs"}
            if self.path not in commands:
                return self.reply(404, {"error": "Unknown route"})
            self.reply(200, service.dispatch({"command": commands[self.path]}))

        def do_POST(self):
            if not self.authorized():
                return
            self.connection.settimeout(5)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_REQUEST:
                    return self.reply(413, {"error": "Invalid body size"})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("Expected a JSON object")
                if self.path == "/v1/speech":
                    return self.reply(202, service.dispatch(body | {"command": "speak"}))
                if self.path == "/v1/playback" and body.get("command") in ("pause", "resume", "toggle", "stop", "seek", "skip", "rate"):
                    return self.reply(200, service.dispatch(body))
                self.reply(404, {"error": "Unknown route or command"})
            except Exception as exc:
                self.reply(400, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server

