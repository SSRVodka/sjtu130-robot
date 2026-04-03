
## SJTU's 130th Anniversary Celebration: Wenbo Building Exhibition Hall Tour Guide Robot Project

Deploy:

1. copy `agent/config/default.yaml` to `agent/config/robot.yaml` and fill the API keys;

2. modify `museum_tour/waypoints.yaml` and fill your waypoints & actions;

3. execute pack script: `./scripts/pack_for_ohos.sh`;

4. send newest `ohos-deploy-xxx.tar.gz` to OpenHarmony device: `hdc file send ./ohos-deploy-xxx.tar.gz /data`;

5. decompress it on OpenHarmony device and run:

   ```sh
   mkdir -p /data/sjtu130-robot/
   mv /data/ohos-deploy-xxx.tar.gz /data/sjtu130-robot
   cd /data/sjtu130-robot
   ./script/boot_agent.sh
   ```

6. (optional) auto boot: modify `/etc/init.cfg` like [`init.cfg.now`](./scripts/init.cfg.now). Add `exec /bin/sh /data/sjtu130-robot/scripts/boot_agent.sh` in `boot` section.

> [!WARNING]
> 
> If you write an invalid `/etc/init.cfg`, your OpenHarmony device will never boot again :(

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

