#!/bin/sh
# RUN ON OpenHarmonyOS Robot

cd /data
source sysdeps.env

cd /data/sjtu130-robot/agent

nohup python3 main.py -c config/robot.yaml serve > /data/sjtu130-robot/agent.log 2>&1 &
