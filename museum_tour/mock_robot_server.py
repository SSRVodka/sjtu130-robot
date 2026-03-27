"""mock_robot_server.py — Flask-based simulation of the Reeman SLAM Web API v3.

End-points implemented (enough for robot_client.py):
    GET  /reeman/current_version   → {"version": "v3.mock"}
    GET  /reeman/pose              → {"x": 0.0, "y": 0.0, "theta": 0.0}
    GET  /reeman/get_mode          → {"mode": 2}
    GET  /reeman/base_encode       → {"battery": 85}
    POST /cmd/nav_name             body {"point": "..."}  → {"status": "success"}
    POST /cmd/nav                 body {"x", "y", "theta"} → {"status": "success"}
    POST /cmd/cancel_goal          body {}               → {"status": "success"}
    GET  /reeman/nav_status        → {"res": 3, "reason": 0, ...}

Navigation commands complete synchronously (res=3, reason=0) so that
wait_for_arrival() returns immediately with True.

Run:
    python -m museum_tour.mock_robot_server       # default :8080
    python -m museum_tour.mock_robot_server 9000  # custom port
"""

from __future__ import annotations

import sys
import threading
import time
from http import HTTPStatus
from typing import Any, Dict

from flask import Flask, jsonify, request

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Mutable robot state (all access guarded by the GIL — safe for single worker)
# ---------------------------------------------------------------------------

_state: Dict[str, Any] = {
    "x": 0.0,
    "y": 0.0,
    "theta": 0.0,
    "mode": 2,
    "battery": 85,
    # navigation state
    "nav_goal": "",
    "nav_active": False,
    "nav_res": 6,     # NavRes.INIT
    "nav_reason": 0,  # InitReason.OK
    "nav_dist": 0.0,
    "nav_mileage": 0.0,
}


def _finish_navigation(success: bool = True, goal: str = "") -> None:
    _state["nav_active"] = False
    _state["nav_res"] = 3   # NavRes.FINISHED
    _state["nav_reason"] = 0 if success else 1  # NavReason.SUCCESS / FAILURE
    _state["nav_goal"] = goal
    _state["nav_dist"] = 0.0


def _start_navigation(goal: str = "") -> None:
    _state["nav_active"] = True
    _state["nav_res"] = 1   # NavRes.STARTED
    _state["nav_reason"] = 0
    _state["nav_goal"] = goal
    _state["nav_dist"] = 0.0


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/reeman/current_version", methods=["GET"])
def current_version():
    return jsonify({"version": "v3.mock"})


@app.route("/reeman/pose", methods=["GET"])
def pose():
    return jsonify({"x": _state["x"], "y": _state["y"], "theta": _state["theta"]})


@app.route("/reeman/get_mode", methods=["GET"])
def get_mode():
    return jsonify({"mode": _state["mode"]})


@app.route("/reeman/base_encode", methods=["GET"])
def base_encode():
    return jsonify({"battery": _state["battery"]})


@app.route("/cmd/nav_name", methods=["POST"])
def nav_name():
    body = request.get_json(silent=True) or {}
    point = body.get("point", "")
    _start_navigation(goal=point)
    # Simulate instant arrival
    _finish_navigation(success=True, goal=point)
    return jsonify({"status": "success"})


@app.route("/cmd/nav", methods=["POST"])
def nav():
    body = request.get_json(silent=True) or {}
    x = float(body.get("x", 0.0))
    y = float(body.get("y", 0.0))
    theta = float(body.get("theta", 0.0))
    _state["x"] = x
    _state["y"] = y
    _state["theta"] = theta
    _start_navigation(goal=f"({x},{y},{theta})")
    # Simulate instant arrival
    _finish_navigation(success=True, goal=f"({x},{y},{theta})")
    return jsonify({"status": "success"})


@app.route("/cmd/cancel_goal", methods=["POST"])
def cancel_goal():
    if _state["nav_active"]:
        _state["nav_active"] = False
        _state["nav_res"] = 4   # NavRes.CANCELLED
    return jsonify({"status": "success"})


@app.route("/reeman/nav_status", methods=["GET"])
def nav_status():
    return jsonify({
        "res": _state["nav_res"],
        "reason": _state["nav_reason"],
        "goal": _state["nav_goal"],
        "dist": _state["nav_dist"],
        "mileage": _state["nav_mileage"],
    })


# ---------------------------------------------------------------------------
# Entry-point
# ---------------------------------------------------------------------------

def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"[mock_robot_server] Starting on http://127.0.0.1:{port}")
    print(f"[mock_robot_server] Initial pose: ({_state['x']}, {_state['y']}, {_state['theta']})")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
