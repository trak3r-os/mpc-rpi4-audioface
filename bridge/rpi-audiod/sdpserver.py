# SPDX-License-Identifier: GPL-3.0-or-later
"""Small read-only HTTP endpoint for the active RTP session description."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import threading


class Server:
    def __init__(self, address, port, path, available):
        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def do_GET(self):
                self.respond(False)

            def do_HEAD(self):
                self.respond(True)

            def respond(self, head):
                route = self.path.split("?", 1)[0]
                if route not in ("/", "/network-rtp.sdp"):
                    self.send_error(404)
                    return
                if route == "/":
                    data = (b'<!doctype html><html lang="en"><meta name="viewport" content="width=device-width">'
                            b'<title>rpi-audio RTP</title><body><h1>rpi-audio</h1>'
                            b'<p><a href="/network-rtp.sdp">Download the RTP session (SDP)</a></p>'
                            b'<p>Enable Network RTP in Outputs first. Open the downloaded file in an RTP/L16 receiver.'
                            b' Audio uses the configured network address and UDP port.</p></body></html>')
                    kind = "text/html; charset=utf-8"
                else:
                    if not available():
                        self.send_error(503, "Enable Network RTP and start the audio engine")
                        return
                    try:
                        data = path.read_bytes()[:8192]
                    except OSError:
                        self.send_error(503, "RTP is starting; retry shortly")
                        return
                    kind = "application/sdp"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                if route.endswith(".sdp"):
                    self.send_header("Content-Disposition", 'attachment; filename="network-rtp.sdp"')
                self.end_headers()
                if not head:
                    self.wfile.write(data)

            def log_message(self, *_):
                pass

        self.http = HTTPServer((address, port), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True)
        self.thread.start()

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=3)
