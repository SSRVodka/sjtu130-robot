
## SJTU's 130th Anniversary Celebration: Wenbo Building Exhibition Hall Tour Guide Robot Project

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

