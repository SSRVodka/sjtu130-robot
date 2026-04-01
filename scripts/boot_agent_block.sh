#!/bin/sh
# RUN ON OpenHarmonyOS Robot

cd /data
source sysdeps.env

cd /data/sjtu130-robot/agent

python3 main.py -c config/robot.yaml serve
