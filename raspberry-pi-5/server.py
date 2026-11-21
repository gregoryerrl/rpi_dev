#!/usr/bin/python3
import base64
import hmac
import json
import secrets
import socket
import ssl
import threading
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from urllib.parse import parse_qs

from network import Controller, validate

ROOT = Path(__file__).resolve().parent
CONFIG = Path("/etc/rpi-setup")
PAGE = Template((ROOT / "page.html").read_text())


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(8)
        self.request = self.server.tls.wrap_socket(self.request, server_side=True)
        super().setup()

    def reply(self, status, body="", **headers):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def authorized(self):
        value = self.headers.get("Authorization", "").encode("latin1")
        if hmac.compare_digest(value, self.server.authorization):
            return True
        self.reply(401, "Sign in with your setup credentials.",
                   **{"WWW-Authenticate": 'Basic realm="Pi setup"'})
        return False

    def page(self, status=200, message=None):
        c = self.server.controller
        self.reply(status, PAGE.substitute(
            hostname=escape(socket.gethostname()), status=escape(c.status),
            message=escape(c.notice if message is None else message),
            details=escape(c.details), hotspot=escape(self.server.hotspot_name), token=self.server.token))

    def do_GET(self):
        if self.path != "/":
            self.reply(404)
        elif self.authorized():
            self.page()

    def do_POST(self):
        if not self.authorized():
            return
        if self.path not in ("/join", "/retry"):
            return self.reply(404)
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            return self.reply(415)
        try:
            size = int(self.headers.get("Content-Length", ""))
            if not 0 < size <= 2048:
                return self.reply(413)
            fields = parse_qs(self.rfile.read(size).decode(), max_num_fields=3)
            if fields.get("token") != [self.server.token]:
                return self.reply(403)
            ssid = fields.get("ssid", [""])[0]
            password = fields.get("password", [""])[0]
            if self.path == "/join":
                validate(ssid, password)
        except (UnicodeError, ValueError) as exc:
            return self.page(400, str(exc))
        if not self.server.controller.submit(self.path[1:], ssid, password):
            return self.page(409, "A network change is already in progress.")
        self.page(202, "Switching networks. Join the same network as the Pi and reopen this page. "
                  "If the connection fails, look for the previous network or the setup hotspot.")

    def log_request(self, code="-", size="-"):
        pass  # Keep form submissions and arbitrary URL text out of the journal.


class Server(ThreadingHTTPServer):
    slots = threading.BoundedSemaphore(12)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request, client_address):
        import sys
        if not isinstance(sys.exception(), (ssl.SSLError, TimeoutError, ConnectionError)):
            super().handle_error(request, client_address)


def main():
    config = json.loads((CONFIG / "config.json").read_text())
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version = ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(CONFIG / "cert.pem", CONFIG / "key.pem")
    controller = Controller(config["hotspot_uuid"])
    with Server(("0.0.0.0", 8443), Handler) as server:
        server.tls = tls
        server.controller = controller
        server.hotspot_name = config["hotspot_ssid"]
        server.authorization = b"Basic " + base64.b64encode(("admin:" + config["admin_password"]).encode())
        server.token = secrets.token_urlsafe(32)
        threading.Thread(target=controller.run, daemon=True).start()
        server.serve_forever()


if __name__ == "__main__":
    main()
