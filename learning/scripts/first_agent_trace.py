import asyncio
from pydantic_ai import Agent, RunContext

roulette = Agent(__import__('os').environ.get('MODEL', 'anthropic:claude-opus-5-5'), deps_type=int, output_type=bool,
                 instructions='Use roulette_wheel.')

@roulette.tool
async def roulette_wheel(ctx: RunContext[int], square: int) -> str:
    """check if the square is a winner"""
    print(f'   [tool runs] square={square!r} ctx.deps={ctx.deps!r} run_step={ctx.run_step}')
    return 'win' if square == ctx.deps else 'lose'

async def main():
    async with roulette.iter('Bet on 18', deps=18) as run:
        async for node in run:
            print('NODE:', type(node).__name__)
    r = run.result
    print('\nOUTPUT:', repr(r.output), '\nUSAGE:', r.usage)
    print('\nMESSAGES:')
    for m in r.all_messages():
        print(' ', type(m).__name__)
        for p in m.parts:
            print('    ', type(p).__name__, {k: v for k, v in vars(p).items() if k in ('content','tool_name','args','tool_call_id')} if hasattr(p,'__dict__') else p)

asyncio.run(main())
