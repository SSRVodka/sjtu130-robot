#!/usr/bin/env python3
"""
Agent Framework – main entry point.

Usage:
  python main.py chat                 # interactive REPL
  python main.py serve                # start web API server
  python main.py ask "Hello world"    # single-shot query
  python main.py sessions             # list persisted sessions
  python main.py clear <session_id>   # clear a session
"""

from __future__ import annotations

import asyncio
import logging
import sys

import click
import uvicorn

from src import (
    Agent, AgentConfig, LLMClient, MCPManager, Memory, ToolRegistry, load_config
)
from src.interfaces.api import create_app
from src.interfaces.cli import run_cli, _run_once
from src.multimodal import build_user_message

logger = logging.getLogger("agent.main")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# App bootstrapper
# ---------------------------------------------------------------------------

async def _build_app(config_path: str) -> tuple[Agent, AgentConfig, MCPManager, Memory]:
    logger.info("Loading config from '%s'", config_path)
    cfg = load_config(config_path)
    logger.debug(
        "Config loaded – LLM model=%s, max_iterations=%d, db=%s",
        cfg.llm.model,
        cfg.max_iterations,
        cfg.memory.db_path,
    )

    logger.debug("Initializing Memory")
    memory = Memory(cfg.memory)
    await memory.initialize()

    logger.debug("Starting MCP manager (%d server(s))", len(cfg.tools.mcp_servers))
    mcp_manager = MCPManager(cfg.tools.mcp_servers)
    await mcp_manager.start()
    connected_servers = sum(
        1 for cfg_ in cfg.tools.mcp_servers
        if any(c.config.name == cfg_.name for c in mcp_manager._connections.values())
    )
    logger.info(
        "MCP manager started – %d/%d server(s) connected",
        connected_servers,
        len(cfg.tools.mcp_servers),
    )

    llm = LLMClient(cfg.llm)
    registry = ToolRegistry(mcp_manager)
    agent = Agent(cfg, llm, memory, registry)

    return agent, cfg, mcp_manager, memory


async def _teardown(mcp_manager: MCPManager, memory: Memory) -> None:
    logger.debug("Tearing down – stopping MCP manager")
    await mcp_manager.stop()
    logger.debug("Tearing down – closing memory")
    await memory.close()
    logger.info("Shutdown complete")


# ---------------------------------------------------------------------------
# Click commands
# ---------------------------------------------------------------------------

@click.group()
@click.option(
    "--config", "-c",
    default="config/default.yaml",
    show_default=True,
    help="Path to YAML configuration file.",
)
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@cli.command()
@click.pass_context
def chat(ctx: click.Context) -> None:
    """Start an interactive REPL chat session."""

    async def _main():
        agent, cfg, mcp, mem = await _build_app(ctx.obj["config_path"])
        try:
            await run_cli(agent, cfg)
        finally:
            await _teardown(mcp, mem)

    asyncio.run(_main())


@cli.command()
@click.argument("text", nargs=-1)
@click.option("--image", "-i", multiple=True, help="Image file path or URL.")
@click.option("--audio", "-a", multiple=True, help="Audio file path.")
@click.option("--session", "-s", default=None, help="Session ID.")
@click.option("--no-stream", is_flag=True, help="Disable streaming output.")
@click.pass_context
def ask(
    ctx: click.Context,
    text: tuple,
    image: tuple,
    audio: tuple,
    session: str | None,
    no_stream: bool,
) -> None:
    """Send a single message and print the response."""

    async def _main():
        agent, cfg, mcp, mem = await _build_app(ctx.obj["config_path"])
        sid = session or cfg.interfaces.cli.session_id
        stream = cfg.interfaces.cli.stream and not no_stream
        query = " ".join(text) if text else ""
        try:
            await _run_once(
                agent, sid, query, list(image), list(audio), stream
            )
        finally:
            await _teardown(mcp, mem)

    asyncio.run(_main())


@cli.command()
@click.option("--host", "-H", default=None, help="Override listen host.")
@click.option("--port", "-p", default=None, type=int, help="Override listen port.")
@click.option("--reload", is_flag=True, help="Enable auto-reload (dev mode).")
@click.pass_context
def serve(
    ctx: click.Context,
    host: str | None,
    port: int | None,
    reload: bool,
) -> None:
    """Start the OpenAI-compatible web API server."""

    async def _main():
        agent, cfg, mcp, mem = await _build_app(ctx.obj["config_path"])
        app = create_app(agent, cfg, mcp=mcp, mem=mem)
        api_cfg = cfg.interfaces.api
        listen_host = host or api_cfg.host
        listen_port = port or api_cfg.port
        click.echo(
            f"Starting server on http://{listen_host}:{listen_port}  "
            f"(model={cfg.llm.model})"
        )
        config = uvicorn.Config(
            app, host=listen_host, port=listen_port, reload=reload, log_level="warning"
        )
        server = uvicorn.Server(config)
        # Teardown (mcp.stop + mem.close) runs inside uvicorn's lifespan,
        # so it is always called inside the same event loop that owns the
        # stdio_client async generators — no cross-task cancel-scope errors.
        await server.serve()

    asyncio.run(_main())


@cli.command()
@click.pass_context
def sessions(ctx: click.Context) -> None:
    """List all persisted sessions."""

    async def _main():
        cfg = load_config(ctx.obj["config_path"])
        mem = Memory(cfg.memory)
        await mem.initialize()
        rows = await mem.list_sessions()
        await mem.close()
        if not rows:
            click.echo("No sessions found.")
        else:
            click.echo(f"{'SESSION ID':<40} {'UPDATED AT'}")
            click.echo("-" * 60)
            import datetime
            for r in rows:
                ts = datetime.datetime.fromtimestamp(r["updated_at"]).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                click.echo(f"{r['session_id']:<40} {ts}")

    asyncio.run(_main())


@cli.command("clear")
@click.argument("session_id")
@click.pass_context
def clear_session(ctx: click.Context, session_id: str) -> None:
    """Clear history for a session."""

    async def _main():
        cfg = load_config(ctx.obj["config_path"])
        mem = Memory(cfg.memory)
        await mem.initialize()
        await mem.clear(session_id)
        await mem.close()
        click.echo(f"Session '{session_id}' cleared.")

    asyncio.run(_main())


if __name__ == "__main__":
    cli()
