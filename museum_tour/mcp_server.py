"""mcp_server.py — MCP Server exposing museum tour probe functionality.

Provides three MCP tools mirroring the HTTP probe endpoints:
  - get_status   (GET /status)
  - start_tour   (PUT /tour?dst=...)
  - reset_tour   (PUT /reset)

The probe HTTP server (ThreadingHTTPServer) can be started simultaneously on a
separate port so that both MCP and plain HTTP clients can control the same
controller.

Supported MCP transports:
  - stdio
  - streamable-http

Usage
-----
    # MCP over stdio + probe on :8080
    python -m museum_tour.mcp_server --config waypoints.yaml

    # MCP over streamable-http + probe on :8080
    python -m museum_tour.mcp_server --config waypoints.yaml \\
        --transport streamable-http --host-mcp 0.0.0.0 --port 8000

    # MCP only, no probe
    python -m museum_tour.mcp_server --config waypoints.yaml --no-probe

    # Override robot host
    python -m museum_tour.mcp_server --config waypoints.yaml \\
        --host 192.168.1.100
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from typing import TYPE_CHECKING, Any

from mcp.server.fastmcp import FastMCP

from config import load_config
from robot_client import RobotClient
from tour_controller import TourController

if TYPE_CHECKING:
    from probe import ProbeServer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

def register_mcp_tools(mcp: FastMCP, controller: TourController) -> None:
    """Register get_status / start_tour / reset_tour on an existing FastMCP."""
    client = controller.client

    # ------------------------------------------------------------------
    # Tool: get_status
    # ------------------------------------------------------------------
    @mcp.tool(
        name="get_status",
        title="Get Tour Status",
        description=(
            "Return the current tour state: current waypoint name, "
            "whether audio is playing, whether the robot is waiting at a "
            "waypoint, and the robot's live map coordinates (x, y, theta)."
        ),
    )
    def get_status() -> dict[str, Any]:
        try:
            loc = client.get_pose()
            location = {"x": loc.x, "y": loc.y, "theta": loc.theta}
        except Exception as exc:
            logger.debug("Could not fetch robot pose: %s", exc)
            location = None

        snap = controller.state.snapshot()
        return {
            "current_waypoint": snap["waypoint"],
            "audio_playing": snap["audio_playing"],
            "robot_waiting": snap["phase"] == "dwelling",
            "robot_location": location,
        }

    # ------------------------------------------------------------------
    # Tool: start_tour
    # ------------------------------------------------------------------
    @mcp.tool(
        name="start_tour",
        title="Start / Restart Tour",
        description=(
            "Interrupt any running tour and restart from the named waypoint, "
            "then proceed sequentially through all subsequent waypoints. "
            "Returns an error if the waypoint name is not recognised. "
            "Use get_status to discover the list of available waypoints."
        ),
    )
    def start_tour(waypoint_name: str) -> dict[str, Any]:
        if controller.jump_to(waypoint_name):
            return {"status": "ok", "jumping_to": waypoint_name}
        else:
            known = [wp.name for wp in controller.config.waypoints]
            return {
                "status": "error",
                "message": f"Waypoint '{waypoint_name}' not found.",
                "available_waypoints": known,
            }

    # ------------------------------------------------------------------
    # Tool: reset_tour
    # ------------------------------------------------------------------
    @mcp.tool(
        name="reset_tour",
        title="Reset Tour",
        description=(
            "Immediately interrupt any running tour and reset the tour "
            "controller to idle state. The robot will stop and remain at "
            "its current position."
        ),
    )
    def reset_tour() -> dict[str, Any]:
        controller.reset()
        return {"status": "ok"}


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="MCP Server for museum guided-tour controller",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--config", default="waypoints.yaml", metavar="FILE",
        help="Tour YAML configuration file.",
    )
    p.add_argument(
        "--host", metavar="IP",
        help="Override the robot host IP from the config file.",
    )
    # MCP transport
    p.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio", "streamable-http"],
        help="MCP transport protocol.",
    )
    p.add_argument(
        "--host-mcp", dest="mcp_host", default="0.0.0.0", metavar="IP",
        help="Address the MCP server listens on (streamable-http only).",
    )
    p.add_argument(
        "--port", type=int, default=8000, metavar="N",
        help="TCP port the MCP server listens on (streamable-http only).",
    )
    # Probe HTTP server
    p.add_argument(
        "--no-probe", dest="no_probe", action="store_true",
        help="Disable the HTTP probe server.",
    )
    p.add_argument(
        "--probe-host", default="0.0.0.0", metavar="IP",
        help="Address the HTTP probe server listens on.",
    )
    p.add_argument(
        "--probe-port", type=int, default=8080, metavar="N",
        help="TCP port the HTTP probe server listens on.",
    )
    # Logging
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.log_level)

    # Build controller (shared by both MCP and probe)
    config = load_config(args.config)
    if args.host:
        config.robot.host = args.host
        logger.info("Robot host overridden to %s", args.host)

    client = RobotClient(host=config.robot.host)
    controller = TourController(config=config, client=client)
    controller.start()

    # Build FastMCP and register tools
    mcp = FastMCP(
        name="museum-tour",
        instructions=(
            "Museum guided-tour controller for a REEMAN robot. "
            "Use get_status to inspect the current waypoint, audio state, "
            "and robot pose. Use start_tour to begin or restart a tour "
            "from a named waypoint. Use reset_tour to abort the tour "
            "and return the controller to idle."
        ),
        host="0.0.0.0",
        port=8000,
    )
    register_mcp_tools(mcp, controller)

    # Start probe HTTP server (daemon thread)
    probe_server: "ProbeServer | None" = None
    if not args.no_probe:
        from probe import ProbeServer
        probe_server = ProbeServer(
            host=args.probe_host,
            port=args.probe_port,
            controller=controller,
        )
        probe_server.start()
        logger.info(
            "Probe HTTP server listening on http://%s:%d  "
            "(GET /status  PUT /tour?dst=...  PUT /reset)",
            args.probe_host, args.probe_port,
        )

    # Graceful shutdown
    def _on_signal(sig: int, _frame: object) -> None:
        logger.info("Signal %d received — shutting down.", sig)
        controller.shutdown()
        if probe_server:
            probe_server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    # Run MCP transport (blocks until server exits)
    if args.transport == "streamable-http":
        mcp.settings.host = args.mcp_host
        mcp.settings.port = args.port
        logger.info(
            "Starting MCP server (streamable-http) on http://%s:%d ...",
            args.mcp_host, args.port,
        )
        mcp.run(transport="streamable-http")
    else:
        logger.info("Starting MCP server (stdio) ...")
        mcp.run(transport="stdio")

    # Unreachable for stdio; reached for streamable-http when server exits
    if probe_server:
        probe_server.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
