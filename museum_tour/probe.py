"""probe.py — HTTP probe server for status inspection and tour control.

Endpoints
---------
GET /status
    Returns the current waypoint, audio state, robot waiting flag,
    and the robot's live map coordinates.

PUT /tour?dst={name}
    Immediately interrupts any running tour and restarts from the named
    waypoint, proceeding sequentially from that point.

PUT /reset
    Immediately interrupts any running tour and resets the tour controller to idle state.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    from tour_controller import TourController

logger = logging.getLogger(__name__)


class ProbeServer:
    """Lightweight HTTP probe that wraps :class:`TourController`."""

    def __init__(self, host: str, port: int, controller: "TourController") -> None:
        self.host = host
        self.port = port
        self.controller = controller
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        """Start serving in a background daemon thread."""
        controller = self.controller

        class _Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):  # suppress default stderr log
                logger.debug("probe: " + format, *args)

            def _send_json(self, code: int, body: dict) -> None:
                data = json.dumps(body, indent=2).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                logger.debug("do_GET: %s", self.path)
                if self.path != "/status":
                    self._send_json(404, {"error": "Not found"})
                    return

                try:
                    loc = controller.client.get_pose()
                    location = {"x": loc.x, "y": loc.y, "theta": loc.theta}
                except Exception as exc:
                    logger.debug("Could not fetch robot pose: %s", exc)
                    location = None

                snap = controller.state.snapshot()
                self._send_json(200, {
                    "current_waypoint": snap["waypoint"],
                    "audio_playing":    snap["audio_playing"],
                    "robot_waiting":    snap["phase"] == "dwelling",
                    "robot_location":   location,
                })

            def do_PUT(self):
                logger.debug("do_PUT: %s", self.path)
                parsed = urlparse(self.path)

                if parsed.path == "/reset":
                    controller.reset()
                    self._send_json(200, {"status": "ok"})
                    return
                elif parsed.path != "/tour":
                    self._send_json(404, {"error": "Not found"})
                    return

                dst = (parse_qs(parsed.query).get("dst") or [None])[0]
                if not dst:
                    self._send_json(400, {"error": "Missing required parameter: dst"})
                    return

                if controller.jump_to(dst):
                    self._send_json(200, {"status": "ok", "jumping_to": dst})
                else:
                    known = [wp.name for wp in controller.config.waypoints]
                    self._send_json(404, {
                        "error": f"Waypoint '{dst}' not found.",
                        "available": known,
                    })

        self._server = ThreadingHTTPServer((self.host, self.port), _Handler)
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        logger.info("Probe server listening on http://%s:%d", self.host, self.port)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
