
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


About the agent: [The README for agent](./agent/README.md)

