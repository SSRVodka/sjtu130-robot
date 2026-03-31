#!/bin/sh
# RUN ON OpenHarmonyOS Robot

cd /data

source ./sysdeps.env

REPO_ROOT=/data/sjtu130-robot

/data/out/bin/python3 $REPO_ROOT/museum_tour/mcp_server.py \
	--config $REPO_ROOT/museum_tour/waypoints.yaml \
	--transport stdio

