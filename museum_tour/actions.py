"""actions.py — Stub registry for human-robot interaction functions.

Each action is a plain Python function that accepts the robot client and the
current waypoint name.  Register new actions with ``@register`` and they will
be picked up automatically when named in the YAML ``actions`` list.

To implement a real action, replace the body of the stub (or add a new
function) and keep the signature::

    def my_action(client: RobotClient, waypoint_name: str) -> None:
        ...
"""

from __future__ import annotations

import logging
from typing import Callable, Dict

from robot_client import RobotClient

logger = logging.getLogger(__name__)

# action_name -> callable
_REGISTRY: Dict[str, Callable[[RobotClient, str], None]] = {}


def register(name: str) -> Callable:
    """Decorator that registers a function under *name*."""
    def decorator(fn: Callable[[RobotClient, str], None]) -> Callable:
        _REGISTRY[name] = fn
        return fn
    return decorator


def run_action(name: str, client: RobotClient, waypoint_name: str) -> None:
    """Execute a registered action by name, or warn if unknown."""
    fn = _REGISTRY.get(name)
    if fn is None:
        logger.warning("Unknown action '%s' at waypoint '%s' — skipping.", name, waypoint_name)
        return
    logger.info("Running action '%s' at '%s'.", name, waypoint_name)
    fn(client, waypoint_name)


# ---------------------------------------------------------------------------
# Stub implementations
# ---------------------------------------------------------------------------


@register("greet")
def action_greet(client: RobotClient, waypoint_name: str) -> None:
    """Wave or trigger a greeting animation/sound."""
    # TODO: send serial command or HTTP request to actuate greeting gesture
    logger.info("[STUB] greet at '%s'", waypoint_name)


@register("farewell")
def action_farewell(client: RobotClient, waypoint_name: str) -> None:
    """Play a farewell gesture at the end of the tour."""
    # TODO: trigger farewell animation
    logger.info("[STUB] farewell at '%s'", waypoint_name)


@register("display_artifact")
def action_display_artifact(client: RobotClient, waypoint_name: str) -> None:
    """Signal an external display or projector to show artifact info."""
    # TODO: send HTTP/serial signal to AV system
    logger.info("[STUB] display_artifact at '%s'", waypoint_name)
