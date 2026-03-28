"""mcp_server.py — MCP Server exposing museum tour probe functionality.

Provides three tools mirroring the HTTP probe endpoints:
  - get_status   (GET /status)
  - start_tour   (PUT /tour?dst=...)
  - reset_tour   (PUT /reset)

Supported transports:
  - stdio
  - streamable-http

Transport and listen address are controlled entirely by command-line flags so
that the server can be started without touching the YAML config.

Usage (stdio)
-------------
    python -m museum_tour.mcp_server --config waypoints.yaml

Usage (streamable-http)
-----------------------
    python -m museum_tour.mcp_server --config waypoints.yaml \\
        --transport streamable-http --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP

from config import load_config
from robot_client import RobotClient
from tour_controller import TourController

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# FastMCP app (built once, run twice depending on transport)
# ---------------------------------------------------------------------------

def build_mcp_app(config_path: str, robot_host: str | None) -> FastMCP:
    """Construct and return a FastMCP instance wired to the tour controller."""
    config = load_config(config_path)
    if robot_host:
        config.robot.host = robot_host
        logger.info("Robot host overridden to %s", robot_host)

    client = RobotClient(host=config.robot.host)
    controller = TourController(config=config, client=client)
    controller.start()

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

    return mcp


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
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
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.log_level)

    mcp = build_mcp_app(args.config, args.host)

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

    return 0


if __name__ == "__main__":
    sys.exit(main())
