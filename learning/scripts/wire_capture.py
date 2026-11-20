import json, httpx2 as httpx
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

def capture(label, fake):
    def handler(req: httpx.Request):
        print(f'===== {label}: POST {req.url}'); print(json.dumps(json.loads(req.content), indent=1)); return httpx.Response(200, json=fake)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))

ant_fake = {"id":"m1","type":"message","role":"assistant","model":"claude-sonnet-5-5","stop_reason":"tool_use",
 "content":[{"type":"tool_use","id":"tu1","name":"final_result","input":{"response":True}}],"usage":{"input_tokens":1,"output_tokens":1}}
oai_fake = {"id":"c1","object":"chat.completion","created":0,"model":"gpt-5","choices":[{"index":0,"finish_reason":"tool_calls",
 "message":{"role":"assistant","content":None,"tool_calls":[{"id":"c1","type":"function","function":{"name":"final_result","arguments":"{\"response\": true}"}}]}}],
 "usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}

models = [('ANTHROPIC', AnthropicModel('claude-sonnet-5-5', provider=AnthropicProvider(api_key='x', http_client=capture('ANTHROPIC', ant_fake)))),
          ('OPENAI', OpenAIChatModel('gpt-5', provider=OpenAIProvider(api_key='x', http_client=capture('OPENAI', oai_fake))))]
for label, m in models:
    a = Agent(m, deps_type=int, output_type=bool, instructions='Use roulette_wheel.')
    @a.tool
    async def roulette_wheel(ctx: RunContext[int], square: int) -> str:
        """check if the square is a winner"""
        return 'win'
    try:
        a.run_sync('Bet on 18', deps=18)
    except Exception as e:
        print('(stopped:', type(e).__name__, ')')
