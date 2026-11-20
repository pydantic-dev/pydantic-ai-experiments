"""Print every HTTP request body Pydantic AI sends to Anthropic: the exact 'prompt' as the API receives it.

Run:  set -a; . ./.env; set +a; .venv/bin/python learning/scripts/show_prompt.py
"""
import json, os
import httpx2
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

n = 0
async def log_request(request: httpx2.Request):
    global n; n += 1
    body = json.loads(request.content)
    print(f'\n========== REQUEST {n}: {request.method} {request.url}')
    print(json.dumps(body, indent=2, ensure_ascii=False))

http = httpx2.AsyncClient(event_hooks={'request': [log_request]}, timeout=120)
model = AnthropicModel('claude-opus-5-5', provider=AnthropicProvider(api_key=os.environ['ANTHROPIC_API_KEY'], http_client=http))

roulette = Agent(model, deps_type=int, output_type=bool, instructions='Use roulette_wheel.')

@roulette.tool
async def roulette_wheel(ctx: RunContext[int], square: int) -> str:
    """check if the square is a winner"""
    return 'win' if square == ctx.deps else 'lose'

r = roulette.run_sync('Bet on 18', deps=18)
print('\nOUTPUT:', r.output, '| cost $', r.usage.cost)
