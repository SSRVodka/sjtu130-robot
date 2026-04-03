
## SJTU's 130th Anniversary Celebration: Wenbo Building Exhibition Hall Tour Guide Robot Project

Deploy (robot using 曦胧机器人):

1. Copy `agent/config/default.yaml` to `agent/config/robot.yaml`, fill the API keys and configure the necessary IP and ports;

2. Modify `museum_tour/waypoints.yaml` and fill your waypoints (on map), necessary IP, ports & actions;

3. Execute pack script: `./scripts/pack_for_ohos.sh`;

4. Send newest `ohos-deploy-xxx.tar.gz` to OpenHarmony device: `hdc file send ./ohos-deploy-xxx.tar.gz /data`;

5. Send Python 3.12 env to OpenHarmony device (use precompiled python binaries. See [release](https://github.com/SSRVodka/sjtu130-robot/releases)): `hdc file send ./ohos-20-python3.12-env-xxx.tar.gz /data`;

   > [!NOTE]
   >
   > You can build the python binaries manually for OpenHarmony using [`ohloha`](https://gitcode.com/openharmony-robot/tools_ohloha);

6. Decompress them on OpenHarmony device:

   ```sh
   # 0. enter OpenHarmony shell
   hdc tconn <you-device-ip>:55555
   hdc shell
   mkdir -p /data/sjtu130-robot/
   mv /data/ohos-deploy-xxx.tar.gz /data/sjtu130-robot
   # 1. decompress the python env just to /data
   cd /data
   tar -zxpvf ohos-20-python3.12-env-xxx.tar.gz
   # tips. If you want to use the REPL, manually source ./sysdeps.env
   # 2. decompress the project under /data/sjtu130-robot
   cd /data/sjtu130-robot
   tar -zxpvf ohos-deploy-xxx.tar.gz
   ```

7. Preparing python env on OpenHarmony device:

   ```sh
   cd /data
   # use this
   source ./sysdeps.env
   cd /data/sjtu130-robot
   python3 -m pip install -r museum_tour/requirements.txt
   python3 -m pip install -r agent/requirements.txt
   ```

8. **Now run the agent on the OpenHarmony device**: `./scripts/boot_agent.sh`.

9. (**optional**) Start ArkUI on HarmonyOS phone: control the robot manually or chat with the agent!

   Compiled HarmonyOS Package here: [sjtu130-robot-ui - Release](https://github.com/SSRVodka/sjtu130-robot-ui/releases);

10. (**optional**) Auto boot on the robot: modify `/etc/init.cfg` like [`init.cfg.now`](./scripts/init.cfg.now). Add `exec /bin/sh /data/sjtu130-robot/scripts/boot_agent.sh` in `boot` section.

   > [!WARNING]
   >
   > If you write an invalid `/etc/init.cfg`, your OpenHarmony device will never boot again :(
   >
   > `/etc/init.cfg` use strict JSON format (no trailing commas, no comments), and **NO blocking commands**.

---

Run tests: `python3 -m pytest`

Run chassis mock: `python3 museum_tour/mock_robot_server.py <port>`

Run tour main: `python3 museum_tour/main.py --config museum_tour/waypoints.yaml --log-level DEBUG`

Run tour controller as a MCP server:

```bash
# stdio mode (default)
python3 museum_tour/mcp_server.py --config waypoints.yaml

# streamable-http mode
python3 museum_tour/mcp_server.py \
    --config waypoints.yaml \
    --transport streamable-http \
    --host-mcp 0.0.0.0 \
    --port 8000
```

**<u>Main Entry</u>** on OpenHarmony Device: `./scripts/boot_agent_block.sh`.


About the agent: [The README for agent](./agent/README.md)

About the ArkUI controller (frontend) on HarmonyOS 6+: [sjtu130-robot-ui](https://github.com/SSRVodka/sjtu130-robot-ui.git). The UI supports:

- Manual Navigation to Waypoints;
- STT -> Agent -> TTS;
- STT -> Agent -> AI Navigation;

### Techs

1. Local inference of STT models on OpenHarmony edge devices;

2. Qwen cloud-based TTS models;

3. Agent framework + MCP tools;


**All code can run on OpenHarmony and HarmonyOS devices**.


### Credits

- Local STT inference using [sense-voice.cpp](https://github.com/lovemefan/SenseVoice.cpp);

