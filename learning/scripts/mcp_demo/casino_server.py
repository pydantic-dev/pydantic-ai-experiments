"""A tiny MCP server (stdio). It logs to stderr whenever the client calls it."""
import sys
from fastmcp import FastMCP

mcp = FastMCP('casino', instructions='Casino tools. Always check table limits before betting.')

def log(msg): print(f'      [MCP server] {msg}', file=sys.stderr, flush=True)

@mcp.tool
def table_limits(table: int) -> str:
    """Get the minimum and maximum stake for a roulette table."""
    log(f'tools/call table_limits(table={table})')
    return f'Table {table}: min 5 EUR, max 500 EUR'

@mcp.tool
def spin(square: int, stake: float) -> str:
    """Bet a stake on one square and spin the wheel once."""
    log(f'tools/call spin(square={square}, stake={stake})')
    return 'win' if square == 18 else 'lose'

if __name__ == '__main__':
    log('process started')
    mcp.run(show_banner=False)
