"""main.py — Entry point for the museum guided-tour controller.

The program starts idle.  Use the probe to begin a tour:

    PUT http://<probe_host>:<probe_port>/tour?dst=<waypoint_name>

Usage
-----
    python main.py --config waypoints.yaml
    python main.py --config waypoints.yaml --host 192.168.1.100
    python main.py --config waypoints.yaml --log-level DEBUG
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from config import load_config
from probe import ProbeServer
from robot_client import RobotClient
from tour_controller import TourController


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Reeman robot museum guided-tour controller",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config", default="waypoints.yaml", metavar="FILE",
                   help="Tour YAML configuration file.")
    p.add_argument("--host", metavar="IP",
                   help="Override the robot host IP from the config file.")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    try:
        config = load_config(args.config)
    except Exception as exc:
        logger.error("Failed to load config '%s': %s", args.config, exc)
        return 1

    if args.host:
        config.robot.host = args.host
        logger.info("Robot host overridden to %s", args.host)

    client     = RobotClient(host=config.robot.host)
    controller = TourController(config=config, client=client)
    probe      = ProbeServer(host=config.probe.host, port=config.probe.port,
                             controller=controller)

    controller.start()
    probe.start()

    logger.info(
        "Ready. PUT http://%s:%d/tour?dst=<waypoint> to start.",
        config.probe.host, config.probe.port,
    )

    def _on_signal(sig: int, _frame: object) -> None:
        logger.info("Signal %d received — shutting down.", sig)
        controller.shutdown()
        probe.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    while True:          # keep main thread alive; all work happens in daemon threads
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
