"""Same agent, with and without prompt caching, on Opus. Prints per-request token usage and total cost.

Run:  set -a; . ./.env; set +a; .venv/bin/python learning/scripts/cache_demo.py
"""
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Caching
from pydantic_ai.messages import ModelResponse

# ~6k tokens of "house rules", above Anthropic's minimum cacheable length
HANDBOOK = 'Casino house rules.\n' + '\n'.join(
    f'Rule {i}: table {i % 12} accepts stakes between {i % 7 + 1} and {i % 50 + 100} EUR; '
    f'dealer rotation every {i % 9 + 10} minutes; payouts are verified by the pit boss on duty.'
    for i in range(1, 220))

def make(caching: bool) -> Agent:
    agent = Agent('anthropic:claude-opus-5-5', deps_type=int, instructions=HANDBOOK,
                  capabilities=[Caching()] if caching else [])
    @agent.tool
    async def roulette_wheel(ctx: RunContext[int], square: int) -> str:
        """Spin once with a bet on one square. Returns win or lose."""
        return 'win' if square == ctx.deps else 'lose'
    return agent

for caching in (False, True):
    print(f'\n===== caching={caching}')
    r = make(caching).run_sync('Bet on 3, then 7, then 18, one spin at a time. Then summarise.', deps=18)
    for i, m in enumerate(r.all_messages()):
        if isinstance(m, ModelResponse):
            u = m.usage
            print(f'  request: input={u.input_tokens:>5}  cache_write={u.cache_write_tokens:>5}  cache_read={u.cache_read_tokens:>5}  output={u.output_tokens}')
    print(f'  requests={r.usage.requests}  TOTAL COST ${r.usage.cost:.4f}')
