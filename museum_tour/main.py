"""main.py — Entry point for the museum guided tour controller.

Usage
-----
    python main.py --config waypoints.yaml
    python main.py --config waypoints.yaml --host 192.168.1.100
    python main.py --config waypoints.yaml --no-wait
    python main.py --config waypoints.yaml --log-level DEBUG
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

from config import load_config
from robot_client import RobotClient
from tour_controller import TourController


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)-8s] %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reeman robot museum guided-tour controller",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        default="waypoints.yaml",
        metavar="FILE",
        help="Path to the tour YAML configuration file.",
    )
    parser.add_argument(
        "--host",
        metavar="IP",
        help="Override the robot host IP from the config file.",
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        default=False,
        help="Disable operator wait; robot auto-advances after dwell_time.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    # Load config
    try:
        config = load_config(args.config)
    except Exception as exc:
        logger.error("Failed to load config '%s': %s", args.config, exc)
        return 1

    # Apply CLI overrides
    if args.host:
        config.robot.host = args.host
        logger.info("Host overridden to %s", args.host)

    if args.no_wait:
        config.tour.wait_for_input = False
        logger.info("wait_for_input disabled via --no-wait")

    # Build client and controller
    client = RobotClient(host=config.robot.host)
    controller = TourController(config=config, client=client)

    # Graceful shutdown on Ctrl-C or SIGTERM
    def _handle_signal(signum: int, _frame: object) -> None:
        logger.info("Signal %d received — requesting tour stop.", signum)
        controller.request_stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    # Run tour
    result = controller.run()
    print("\n" + result.summary())
    return 0 if result.all_succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
