"""Agent + MCP server over stdio. Shows WHEN things happen: connect, tools/list, tool calls, disconnect.

Run:  set -a; . ./.env; set +a; .venv/bin/python learning/scripts/mcp_demo/agent_with_mcp.py
"""
import asyncio, json, os, sys
from pathlib import Path
from fastmcp.client.transports import StdioTransport
from pydantic_ai import Agent
from pydantic_ai.capabilities import Caching
from pydantic_ai.mcp import MCPToolset

here = Path(__file__).parent
casino = MCPToolset(StdioTransport(command=sys.executable, args=[str(here / 'casino_server.py')]), id='casino')
agent = Agent('anthropic:claude-opus-5-5', toolsets=[casino], capabilities=[Caching()])

async def main():
    print('-- entering agent: start MCP subprocess, connect, tools/list')
    async with agent:
        prompt = 'I want to bet 50 EUR on square 18 at table 4.'
        async with agent.iter(prompt) as run:
            async for node in run:
                name = type(node).__name__
                print(f'NODE: {name}')
                if hasattr(node, 'model_response'):
                    for p in node.model_response.parts:
                        if p.part_kind == 'tool-call':
                            print(f'   model asks for: {p.tool_name}({p.args})')
        print('\nOUTPUT:', run.result.output)
        print('cost $', run.result.usage.cost)
    print('2) after `async with agent` exits, the subprocess is stopped')

asyncio.run(main())
