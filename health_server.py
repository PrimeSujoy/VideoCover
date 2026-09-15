# Don't Remove Credit Tg - @NexonBots
# Subscribe YouTube Channel For Amazing Bot https://youtube.com/@NexonBots
# Ask Doubt on telegram @NexonContactBot

"""Small dependency-free health server for web-style deployment platforms."""

import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


logger = logging.getLogger(__name__)
_server = None


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/health"):
            self.send_error(404)
            return

        payload = json.dumps({
            "status": "ok",
            "service": "video-cover-bot"
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format, *args):
        # Platform probes are frequent; keep normal logs focused on the bot.
        return


def start_health_server():
    """Start an HTTP health endpoint when PORT is configured."""
    global _server
    if _server is not None:
        return _server

    port_value = os.environ.get("PORT")
    if not port_value:
        logger.info("PORT is not set; health server is disabled")
        return None

    try:
        port = int(port_value)
        _server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    except (TypeError, ValueError, OSError) as error:
        logger.error("Could not start health server on PORT=%r: %s", port_value, error)
        raise

    thread = threading.Thread(
        target=_server.serve_forever,
        name="health-server",
        daemon=True
    )
    thread.start()
    logger.info("Health server listening on port %s", port)
    return _server
