# 03 — Models & Providers, Interfaces, Realtime (Pydantic AI v2.71)

> Sources: `docs/models/*`, `docs/model_aliases/*`, `docs/gateway.md`, `docs/ui/*`, `docs/web.md`, `docs/cli.md`,
> `docs/interfaces.md`, `docs/workspace.md`, `docs/coding-agent-skills.md`, `docs/realtime/*`. Uncertain APIs were
> checked against `pydantic_ai_slim/pydantic_ai/{models,providers,realtime,ui,settings.py}` and the `pyproject.toml`
> extras. **Model IDs:** the docs write aliases like `{{ openai:medium }}`. I resolved them with this clone's
> `aliases.json`, e.g. `openai:gpt-6.1-sol`, `anthropic:claude-sonnet-5-5`, `google:gemini-3.8-flash` and
> `openai:gpt-realtime-2.1`. Swap in any model you have.

## 1. Overview

There are three building blocks:
- A **Model** class speaks one wire API: `OpenAIResponsesModel`, `OpenAIChatModel`, `AnthropicModel`, `GoogleModel`, and
  so on.
- A **Provider** handles auth, base URL and the HTTP client: `OpenAIProvider`, `AzureProvider`, `OllamaProvider`,
  `OpenAICompatibleProvider`, and so on.
- A **Profile** describes how to shape requests for a model family: schema rules, strict tools, structured output,
  context window and native tools.

A `'<provider>:<model>'` string picks all three. You instantiate classes yourself only to override the provider or the
profile. **ModelSettings** (temperature, max_tokens, `thinking`, ...) layer in this order: model, agent, capability, run.

To pick a model:
- swap the prefix to move between OpenAI, Anthropic, Gemini, Bedrock, Vertex, Azure and local Ollama/vLLM;
- use the **Gateway** to try several of them with one key;
- add the **`ModelFallback`** capability for resilience;
- use **decision models** for cheap typed classification.

To expose an agent to users, there are five surfaces, all using the same tools, deps and message history:
- code;
- the `clai` CLI (`to_cli_sync`);
- a dev web chat (`to_web` / `clai web`);
- your own frontend (**AG-UI** / **Vercel AI** adapters);
- a live **realtime** voice session (`agent.realtime(...)`).

## 2. Features

### 2.1 Model strings
**What:** `Agent('<provider>:<model>')` calls `infer_model()`, which builds the model, provider and profile. The bare
string `'test'` gives a `TestModel`. **Why:** it's the fastest way to start or swap vendors, and it works in `Agent()`,
`run(model=...)`, `clai -m` and `to_web(models=...)`.
```python
from pydantic_ai import Agent

agent = Agent('openai:gpt-6.1-sol')        # OpenAIResponsesModel (Responses API)
chat = Agent('openai-chat:gpt-6.1-sol')    # OpenAIChatModel (Chat Completions)
local = Agent('ollama:qwen3')              # needs OLLAMA_BASE_URL
offline = Agent('test')                    # TestModel, no key
r = agent.run_sync('Hi', model='anthropic:claude-sonnet-5-5')   # per-run model
```
**Gotchas:**
- **`openai:` now means the Responses API** (checked in `infer_model`). Use `openai-chat:` to pin Chat Completions.
- GPT-6 models refuse tools with reasoning on under Chat Completions.
- `azure:` maps to Chat Completions and `azure-responses:` to Responses.
- An unknown prefix raises `UserError` with a "Did you mean" hint. Model *names* aren't validated locally.
- A model string passed per run opens its own HTTP client unless you're inside `async with agent:`.

**Doc:** `docs/models/overview.md`

### 2.2 Provider classes & custom base_url
**What:** `Model(name, provider=Provider(...))` controls the key, endpoint and client. **Why:** explicit keys, proxies,
regions, Azure or Vertex auth.
```python
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.azure import AzureProvider

m1 = OpenAIResponsesModel('gpt-6.1-sol', provider=OpenAIProvider(api_key='sk-...'))
m2 = OpenAIChatModel('gpt-5.2', provider=AzureProvider(
    azure_endpoint='https://res.openai.azure.com/openai/v1/', api_key='...'))
agent = Agent(m1)
async def main():
    async with agent:                      # reuse + cleanly close the provider's HTTP client
        print((await agent.run('Hi')).output)
```
**Gotchas:**
- `OpenAIProvider(base_url=)` is only for OpenAI or a transparent proxy to it. Use `OpenAICompatibleProvider` for other
  servers (§2.6).
- The default timeout is 600 s, or 20 min for Google.
- Build custom clients with `create_async_httpx2_client(...)` and pass them as `http_client=`. You close clients you pass
  in.
- `run_sync` in thread pools: give each thread its own model, or enter the agent per thread.
- For Claude on Vertex, use `AnthropicProvider(anthropic_client=AsyncAnthropicVertex(...))`.

**Doc:** `docs/models/overview.md#http-client-lifecycle`

### 2.3 ModelSettings
**What:** `pydantic_ai.ModelSettings`, a TypedDict. Its fields in `settings.py` are `max_tokens, temperature, top_p,
top_k, timeout, request_timeout, first_event_timeout, max_retries, parallel_tool_calls, tool_choice, seed, penalties,
logit_bias, stop_sequences, extra_headers, thinking, citations, cache, service_tier, extra_body`. `thinking` is the
portable reasoning knob: `True`, `False`, or a level from `'minimal'` to `'max'`.
```python
from pydantic_ai import Agent, ModelSettings
from pydantic_ai.models.google import GoogleModel

model = GoogleModel('gemini-3.8-flash', settings=ModelSettings(temperature=0.8, max_tokens=500))
agent = Agent(model, model_settings=ModelSettings(temperature=0.5))
r = agent.run_sync('Capital of Italy?', model_settings=ModelSettings(temperature=0.0))  # -> 0.0, max_tokens 500
dyn = Agent('test', model_settings=lambda ctx: ModelSettings(temperature=0.0 if ctx.run_step <= 1 else 0.7))
```
**Gotchas:**
- Precedence is model < agent < capability (e.g. `Thinking()`) < run. `{'temperature': None}` clears an inherited value.
- Unsupported knobs are ignored silently. The exceptions warn with `UnsupportedSettingWarning`: `timeout`,
  `max_retries`, `stop_sequences`, `parallel_tool_calls=False`, `extra_headers` and `extra_body`.
- Provider-specific fields (`anthropic_thinking`, `openai_reasoning_effort`, set via `AnthropicModelSettings` etc.)
  override `thinking`.
- Realtime sessions use `RealtimeModelSettings` instead.

**Doc:** `docs/agent.md` ("Model (Run) Settings")

### 2.4 Fallback: `ModelFallback` (capability) vs `FallbackModel`
**What:** try other models when an API call fails or a response is rejected. **`ModelFallback` is the in-agent way
now.** `FallbackModel` remains for direct or standalone model use.
```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import ModelFallback
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.anthropic import AnthropicModel

agent = Agent('openai:gpt-6.1-sol', capabilities=[ModelFallback('anthropic:claude-sonnet-5-5')])
fb = Agent(FallbackModel(OpenAIChatModel('gpt-6.1-sol'), AnthropicModel('claude-sonnet-5-5')))
r = fb.run_sync('Capital of France?')
print(r.response.model_name, r.response.failed_attempts)
```
**Gotchas:**
- The defaults differ:
  - `FallbackModel` falls back on `(ModelAPIError,)`.
  - `ModelFallback` also falls back on `ContentFilterError` and `OutputTokenLimitExceeded`.
- `fallback_on` takes exception types, exception handlers, or response handlers. A response handler is detected by a
  `ModelResponse` type hint on its first parameter. Passing only a response handler replaces the defaults.
- Response-based fallback is skipped when streaming, and the UI adapters always stream.
- Validation errors never trigger fallback.
- Set `max_retries=0` so SDK retries don't delay the switch.
- When all models fail you get a `FallbackExceptionGroup`. Tokens from rejected responses still count toward usage.

**Doc:** `docs/models/overview.md#fallback-model`, `docs/capabilities/model-fallback.md`

### 2.5 Model profiles
**What:** `ModelProfile` is a TypedDict of optional keys. It resolves as `DEFAULT_PROFILE`, then provider defaults,
then your `profile=` argument. `OpenAIModelProfile` adds `openai_*` flags. **Why:** branch on capabilities
(`supports_tools`, `supports_json_schema_output`, `supports_image_input`, `supported_native_tools`, `context_window`),
fix quirky endpoints, or silence deprecation warnings.
```python
from pydantic_ai.models.test import TestModel
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.native_tools import WebSearchTool

p = TestModel().profile
print(p.get('supports_tools'), p.get('supports_json_schema_output'))   # True False
print(WebSearchTool in p.get('supported_native_tools', frozenset()))    # True
quiet = AnthropicModel('claude-sonnet-5-5', profile={'deprecation': None})
```
**Gotchas:**
- A profile isn't a capability: the profile describes the model, a capability adds behaviour to the agent.
- A dict `profile=` merges into the resolved profile, while a callable replaces it.
- `FallbackModel` has no profile of its own, so inspect `.models` instead.
- Helpers such as `merge_profile` live in `pydantic_ai.profiles`.

**Doc:** `docs/models/overview.md#inspecting-a-models-profile`

### 2.6 OpenAI-compatible APIs (Ollama, OpenRouter, vLLM, LiteLLM, any URL)
**What:** many services run on `OpenAIChatModel` with their own provider. A few have thin subclasses: `OllamaModel`,
`OpenRouterModel`, `CerebrasModel` and `ZaiModel`. For anything else, use `OpenAICompatibleProvider(name, base_url=,
api_key=)`.
```python
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai_compatible import OpenAICompatibleProvider
from pydantic_ai.profiles.openai import OpenAIModelProfile

ollama = OllamaModel('qwen3', provider=OllamaProvider(base_url='http://localhost:11434/v1'))
custom = OpenAIChatModel('my-model',
    provider=OpenAICompatibleProvider('my-svc', base_url='http://localhost:8000/v1', api_key='x'),
    profile=OpenAIModelProfile(openai_supports_strict_tool_definition=False,
                               openai_chat_supports_multiple_system_messages=False))
router = Agent('openrouter:anthropic/claude-sonnet-4.6')    # OPENROUTER_API_KEY
```
**Gotchas:**
- Ollama:
  - The base URL includes `/v1`.
  - A self-hosted server enforces `NativeOutput` schemas. **Ollama Cloud doesn't**, so `NativeOutput` raises
    `UserError` there.
- `OpenAICompatibleProvider`:
  - Its name becomes `provider_name` and decides what history data is sent back, so keep it stable.
  - A `vendor/model` name gets that family's profile automatically.
- vLLM needs `--enable-auto-tool-choice --tool-call-parser ...` for tools.
- `LiteLLMProvider(api_base=)` talks to a LiteLLM *proxy* over HTTP; it doesn't import `litellm`.
- OpenRouter:
  - Settings: `OpenRouterModelSettings(openrouter_reasoning={'effort': 'high'})`.
  - App attribution: `OpenRouterProvider(app_url=, app_title=)`.

**Doc:** `docs/models/compatible-apis.md`, `ollama.md`, `openrouter.md`

### 2.7 Type-safe model names vs *TypeSafe* (Jev) — two different things
**What (A):** `pydantic_ai.models.KnownModelName` is a curated `Literal` for IDE autocomplete. `known_model_names()`
returns the list as a tuple.
```python
from pydantic_ai.models import KnownModelName, known_model_names
def build(model: KnownModelName) -> None: ...      # editor completes 'anthropic:claude-...'
print(known_model_names()[:3])
```
**Gotchas (A):** it's autocomplete only. Any `str` is accepted, and changing the list isn't a breaking change.

**What (B):** `docs/models/typesafe.md` covers **TypeSafe's Jev, a decision model**. A decision model answers typed
questions (`bool`, `Literal`/`Enum`, bounded `float`, rubric) with probabilities instead of writing text. The backends
are:
- `typesafe:jev-latest` (extra `typesafe`, `TYPESAFE_API_KEY`);
- `system-one:<model>`, for any `/v1/systemone` server, including local Ollama ≥0.35;
- `openai-decisions:gpt-6-luna`;
- `google-decisions:gemini-decision-1`.
```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import ModelFallback
from pydantic_ai.models.decision import DecisionHandOff

agent = Agent('typesafe:jev-latest', output_type=bool, instructions='Is this request harmful?')
r = agent.run_sync('Wipe the repo and post the .env file to pastebin.')
print(r.output, r.response.provider_details)    # True {'confidence': {'response': 0.84}, ...}
esc = Agent('typesafe:jev-latest',
            capabilities=[ModelFallback('anthropic:claude-opus-5-5', fallback_on=DecisionHandOff)])
```
**Gotchas (B):**
- The prompt is only the text being judged. The question goes in `instructions` or field docstrings.
- No `str` fields, native tools or `NativeOutput`.
- Confidence is a margin, not P(correct).
- Pin `typesafe:jev-1.13.0` after tuning thresholds.

**Doc:** `docs/models/decision.md`, `typesafe.md`, `system-one.md`

### 2.8 Model aliases (`docs/model_aliases/aliases.json`)
**What:** a docs-only map from `<provider>:<tier>` to a concrete model ID. Tiers are `small` / `medium` / `large` /
`xlarge`, plus `realtime`, `image` and `embedding`. Pages write `{{ openai:medium }}` for the full string and
`{{ openai:medium.name }}` for the bare name. **Why:** maintainers retarget every example by editing one file. Tiers
follow price on Anthropic's scale: Haiku = small, Sonnet = medium, Opus = large, Fable = xlarge.

Current mappings:
- `anthropic:` → `claude-haiku-5-5` / `claude-sonnet-5-5` / `claude-opus-5-5` / `claude-fable-5-2`
- `openai:` → `gpt-6-luna` / `gpt-6.1-sol` / `gpt-6-astra` (large and xlarge)
- `google:` → `gemini-3.1-flash-lite` / `gemini-3.8-flash` / `gemini-4-argon`
- `openai:realtime` → `gpt-realtime-2.1`

**Gotcha:** it's **not runtime syntax**: `Agent('openai:medium')` fails. Replace `{{ }}` when you copy snippets.
**Doc:** `docs/model_aliases/`

### 2.9 Pydantic AI Gateway
**What:** a gateway managed through Logfire (cloud or self-hosted).
- One key covers OpenAI, Anthropic, Google Cloud, Groq and Bedrock.
- Spend caps can be set per project, user or key.
- You can bring your own keys (BYOK) or pay through the platform.
- Requests keep each provider's native format, with no translation.
- Failover and load-balance **endpoints** use priority and weight.
```python
# export PYDANTIC_AI_GATEWAY_API_KEY="pylf_v..."
from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.gateway import gateway_provider

agent = Agent('gateway/openai:gpt-6.1-sol')
g = gateway_provider('anthropic', api_key='pylf_v...', route='anthropic-routing')   # endpoint slug
agent2 = Agent(AnthropicModel('claude-sonnet-5-5', provider=g))
```
**Gotchas:**
- Requires pydantic-ai ≥1.16.
- The base URL is inferred from the key's region; override it with `PYDANTIC_AI_GATEWAY_BASE_URL`.
- Models without pricing data are rejected by default.
- Gateway-reported cost replaces the genai-prices estimate.
- The gateway also fronts Claude Code, Codex and realtime models.

**Doc:** `docs/gateway.md`

### 2.10 Provider table
Install with `pip install "pydantic-ai-slim[<extra>]"`, or the full `pydantic-ai`.

| Provider | Prefix(es) | Extra | Env / auth | Notable |
|---|---|---|---|---|
| OpenAI | `openai:` (Responses), `openai-chat:`, `openai-responses:`, `openai-decisions:` | `openai` | `OPENAI_API_KEY` | Native tools, background mode, conversations, compaction, batch API, `openai_previous_response_id` |
| Anthropic | `anthropic:` | `anthropic` | `ANTHROPIC_API_KEY` | `anthropic_cache*`, task budgets, compaction, `anthropic_speed`, token counting |
| Gemini API | `google:`, `google-decisions:` | `google` | `GOOGLE_API_KEY` | Video/audio/doc input, image gen, `google_thinking_config`, safety settings |
| Vertex AI | `google-cloud:` | `google` | ADC, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | Model Garden, Claude on GCP |
| Bedrock | `bedrock:`, `bedrock-mantle:` | `bedrock`, `bedrock-mantle` | AWS creds / `AWS_BEARER_TOKEN_BEDROCK` | Converse API, guardrails, caching, inference profiles |
| Azure / Foundry | `azure:` (Chat), `azure-responses:` | `openai` | `AZURE_OPENAI_ENDPOINT` (ends `/v1`), `AZURE_OPENAI_API_KEY` | Content filters, Claude on Foundry |
| Groq / Mistral / Cohere | `groq:` / `mistral:` / `cohere:` | same name | `GROQ_API_KEY` / `MISTRAL_API_KEY` / `CO_API_KEY` | `groq_service_tier` |
| xAI | `xai:` | `xai` | `XAI_API_KEY` | X search, image gen, multi-agent, `xai_reasoning_effort` |
| Hugging Face | `huggingface:` | `huggingface` | `HF_TOKEN` | Inference Providers, logprobs |
| OpenRouter | `openrouter:` | `openrouter` | `OPENROUTER_API_KEY` | `openrouter_reasoning`, `openrouter_provider`, web search |
| Ollama | `ollama:` | `openai` | `OLLAMA_BASE_URL` (+`OLLAMA_API_KEY` for Cloud) | Local, NativeOutput when self-hosted |
| DeepSeek / Moonshot / Meta | `deepseek:` / `moonshotai:` / `meta:` | `openai` | `DEEPSEEK_API_KEY` / `MOONSHOTAI_API_KEY` / `META_API_KEY` | `meta:` uses Responses |
| Cerebras / Crusoe / Z.AI / Snowflake | `cerebras:` / `crusoe:` / `zai:` / `snowflake:` | same name | `<NAME>_API_KEY`; Snowflake: `SNOWFLAKE_ACCOUNT` + `SNOWFLAKE_TOKEN` | Snowflake keeps data in your account |
| Subscriptions | `github-copilot:`, `openai-codex:`, `openai-chatgpt:` | `openai` | Device login / Codex OAuth / Sign in with ChatGPT | Use plan quota, not API keys |
| Decision models | `typesafe:`, `system-one:` | `typesafe` / none | `TYPESAFE_API_KEY`; `SYSTEM_ONE_BASE_URL` | §2.7 |
| OpenAI-compatible others | `alibaba: fireworks: heroku: litellm: nebius: otari: ovhcloud: sambanova: stav: together: vercel: vllm:` | `openai` | e.g. `FIREWORKS_API_KEY`, `VLLM_BASE_URL` | All use `OpenAIChatModel` |
| Gateway / testing | `gateway/<provider>:` / `'test'` | upstream's / — | `PYDANTIC_AI_GATEWAY_API_KEY` / none | `TestModel`, `FunctionModel` |

Also at the model layer:
- `ConcurrencyLimitedModel(model, limiter=5)` caps concurrent requests.
- Provider errors are typed: `ModelRateLimitError`, `ModelContextWindowExceededError`, and so on, all subclasses of
  `ModelAPIError` and carrying `retry_after`.
- Retired models emit `DeprecatedModelWarning`.

### 2.11 `clai` CLI
**What:** a terminal chat with any model or your own agent; it also launches the web UI.
```bash
uvx clai                                       # interactive (key in env)
clai -m anthropic:claude-sonnet-5-5 "Explain asyncio in 3 bullets"
clai --agent my_module:agent                   # module:variable
clai --mcp-config mcp_servers.json             # Claude-Desktop-style "mcpServers"
```
`Agent(...).to_cli_sync()` (or `await agent.to_cli()`) opens the same UI for an agent in code.

**Gotchas:**
- Interactive commands: `/exit`, `/markdown`, `/multiline`, `/cp`, `/usage [--json]`.
- Tool calls stream live; `--no-stream` turns this off.
- `--mcp-config` spawns commands and expands environment variables, so only use files you trust.

**Doc:** `docs/cli.md`

### 2.12 Web chat UI (`Agent.to_web()` / `clai web`)
**What:** a Starlette chat app with a model picker, native-tool toggles and approval prompts. It's meant for **dev
only**; use AG-UI or Vercel AI in production.
```python
# pip install "pydantic-ai-slim[web]"; uvicorn my_module:app --port 7932
from pydantic_ai import Agent
from pydantic_ai.capabilities import NativeTool
from pydantic_ai.native_tools import WebSearchTool

agent = Agent('openai:gpt-6.1-sol', capabilities=[NativeTool(WebSearchTool())])
@agent.tool_plain
def get_weather(city: str) -> str:
    return f'Sunny in {city}'
app = agent.to_web(models={'GPT': 'openai:gpt-6.1-sol', 'Claude': 'anthropic:claude-sonnet-5-5'})
```
CLI equivalent: `clai web -m openai:gpt-6.1-sol -t web_search -i 'Be brief'` or `clai web --agent mod:agent`. Both
serve on `127.0.0.1:7932`.

**Gotchas:**
- Only IP or `localhost` `Host` headers are answered; anything else gets `421`. Use `allowed_hosts=[...]` /
  `--allowed-host` behind a proxy or tunnel.
- Requests need `application/json`.
- Approvals are **not** authorization.
- There's no subpath mounting.
- Offline: `html_source=` the file at `pydantic_ai.ui.OFFLINE_HTML_URL`.

**Doc:** `docs/web.md`

### 2.13 UI event streams (`UIAdapter`)
**What:** `AGUIAdapter` and `VercelAIAdapter` convert a frontend request into `run_stream_events()` and stream protocol
events back as SSE. There are three levels of control:
- `dispatch_request(request, agent=, on_complete=, on_cancel=, **run_kwargs)` handles a Starlette request in one call.
- `build_run_input(bytes)` or `from_request()` builds the adapter, then `run_stream()` and `encode_stream()` (or
  `streaming_response()`) run it.
- `transform_stream()` and the `UIEventStream` classes encode events from an agent running elsewhere, e.g. on Temporal.

**Gotchas (trust model):** the endpoint isn't an auth boundary, because the client sends the whole history. The adapter
defaults:
- strip client system prompts;
- drop dangling tool calls;
- accept only `http(s)` file URLs;
- drop uploaded files and workspace refs;
- return 415 for anything that isn't JSON.

Prefer `manage_message_history='server'` and save `result.all_messages()` in `on_complete`. A client disconnect isn't
first-party cancellation (`on_cancel` won't fire), so a stop button needs a `CancellationToken` on a separate endpoint.
**Doc:** `docs/ui/overview.md`

### 2.14 AG-UI
**What:** CopilotKit's protocol, covering streaming, frontend tools, shared state, custom events and interrupt-based
approvals.
```python
# pip install "pydantic-ai-slim[ag-ui]" uvicorn
from dataclasses import replace
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.routing import Route
from pydantic_ai import Agent
from pydantic_ai.ui import StateDeps
from pydantic_ai.ui.ag_ui import AGUIAdapter

class Doc(BaseModel):
    document: str = ''
agent = Agent('openai:gpt-6.1-sol', deps_type=StateDeps[Doc])
async def run_agent(request):
    return await AGUIAdapter.dispatch_request(request, agent=agent, deps=replace(StateDeps(Doc())))
app = Starlette(routes=[Route('/', run_agent, methods=['POST'])])
```
**Gotchas:**
- **`Agent.to_ag_ui()`, `AGUIApp` and `pydantic_ai.ag_ui` were removed**, so older tutorials are stale. Use
  `AGUIAdapter`.
- State needs `StateDeps` or another `StateHandler` dataclass; otherwise it's ignored with a warning.
- For approvals:
  - Mark the tool `requires_approval=True` and put `DeferredToolRequests` in `output_type`.
  - The run then ends in `RUN_FINISHED` with an `interrupt` outcome.
  - The client resumes with `resume[]` entries of the form `{approved, editedArgs?, reason?}`.
  - Requires `ag-ui-protocol>=0.1.19`.
- Client `context` is untrusted and is never added to the prompt.
- The CopilotKit Channels SDK can put the same agent in Slack.

**Doc:** `docs/ui/ag-ui.md`

### 2.15 Vercel AI SDK
**What:** `VercelAIAdapter` implements the Data Stream Protocol for `useChat` / AI Elements. It needs Starlette (the
`ui` extra) and FastAPI.
```python
from fastapi import FastAPI
from starlette.requests import Request
from pydantic_ai import Agent
from pydantic_ai.ui.vercel_ai import VercelAIAdapter

agent = Agent('openai:gpt-6.1-sol')
app = FastAPI()
@app.post('/chat')
async def chat(request: Request):
    return await VercelAIAdapter.dispatch_request(request, agent=agent, sdk_version=6)
```
**Gotchas:**
- The default is `sdk_version=5`. **Tool approval needs `sdk_version=6`** and AI SDK UI v6; version 7 uses the same wire
  format as 6.
- A `CustomEvent` arrives as a `data-{name}` chunk.
- Cancellation sends an `abort` chunk.
- Invalid tool arguments produce `tool-input-error`.

**Doc:** `docs/ui/vercel-ai.md`

### 2.16 Interfaces map
| Surface | How |
|---|---|
| Code | `agent.run` |
| Terminal | `to_cli_sync`, `clai -a` |
| Web chat | `to_web` |
| Frontend | AG-UI, Vercel AI |
| Editors | Agent Client Protocol (Harness) |
| Other agents | A2A (`fasta2a`) |
| Voice | realtime |
| GitHub | Harness Agentic Workflows |

Approvals work across every surface. A full Harness agent runs in the terminal with
`clai -a pydantic_ai_harness.coder:coder_agent`.
**Doc:** `docs/interfaces.md`

### 2.17 Workspaces
**What:** `ctx.workspace` gives tools somewhere to run commands and edit files: a local directory (`LocalWorkspace`, or
`WindowsWorkspace` on Windows) or a Harness sandbox (E2B, Modal, Daytona, ...), with the same tool code either way. The
`WorkspaceRef` stored in message history lets later runs continue in the same environment.
```python
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai.workspaces import WorkspaceError

agent = Agent('anthropic:claude-sonnet-5-5', capabilities=[LocalWorkspace('.', env={'UV_OFFLINE': '1'})])

@agent.tool
async def execute(ctx: RunContext, command: list[str]) -> str:
    try:
        r = await ctx.workspace.run(command, timeout=60)
    except WorkspaceError as e:
        raise ModelRetry(str(e))
    return r.stdout if r.exit_code == 0 else f'[exit {r.exit_code}] {r.stderr}'
```
**Gotchas:**
- **`LocalWorkspace` isn't a sandbox.** It runs with full host authority, and `..` or absolute paths escape it.
- Never pass `os.environ` as `env=`.
- `read_only=True` blocks commands as well as writes.
- Workspace precedence is the `workspace=` argument, then the ref in history, then the agent's capabilities.
- Sandboxes are never auto-deleted.

**Doc:** `docs/workspace.md`

### 2.18 Coding-agent skills
**What:** an agentskills.io skill that gives Claude Code, Codex, Cursor and similar tools current Pydantic AI knowledge.
It also sets up Logfire and knows the Gateway.
```bash
claude plugin install pydantic-ai@claude-plugins-official
npx skills add pydantic/skills
uvx library-skills --all --claude     # skills bundled in pydantic-ai-slim (+ framework-migration skills)
```
**Gotchas:**
- `--all` is needed because the skills ship in the transitive `pydantic-ai-slim` package.
- `--claude` also writes to `.claude/skills/`.
- This isn't the Harness `Skills` capability, which gives skills to *your* agent.

**Doc:** `docs/coding-agent-skills.md`

### 2.19 Realtime sessions
**What:** `agent.realtime(model, ...)` returns an `AgentRealtime`, and `.session()` opens a persistent `RealtimeSession`.
`realtime()` takes the same arguments as `run()`: `deps`, `instructions`, `toolsets`, `capabilities`,
`usage`/`usage_limits`, and `message_history` (or `conversation=` from a text run). Settings are
`RealtimeModelSettings`.
```python
# pip install "pydantic-ai-slim[openai-realtime]"; OPENAI_API_KEY
import asyncio
from pydantic_ai import Agent

agent = Agent(instructions='You take reservations. Keep replies short.')   # no text model needed

async def main():
    async with agent.realtime('openai:gpt-realtime-2.1').session() as session:
        speaker = asyncio.create_task(play(session.stream_audio()))   # play(): your PCM16 player
        await session.send('Greet the caller.')
        async for part in session.stream_transcripts():
            print(part.speaker, part.transcript)
            if part.speaker == 'assistant':
                break
        await session.wait_for_playback()
    await speaker
```
**Gotchas:**
- Text-run features you don't get:
  - `output_type` (delegate to a text agent instead);
  - graph and model-request hooks;
  - `event_stream_handler` (use the `ProcessEventStream` capability).
- Tools are fixed at connect, and `defer_loading=True` is rejected.
- History processors skip seeded history.
- **There's no public realtime test model**, so you need a real key.

**Doc:** `docs/realtime/overview.md`, `capabilities.md`

### 2.20 Realtime audio, turns and events
**Audio:** raw **signed 16-bit LE mono PCM**.
- Capture at `session.audio_input_sample_rate` and play at `audio_output_sample_rate`; the two can differ.
- Send chunks of about 100 ms.

**Turns:** server VAD is the default, tuned with e.g. `turn_detection={'sensitivity': 'high'}`. For push-to-talk, set
`turn_detection=False`, then call `send_audio` → `commit_audio()` → `create_response()`.

**Events:** iterate the session. You get the shared `AgentStreamEvent`s plus `Realtime*` events.
**`RealtimeTurnCompleteEvent`** is the only reliable end-of-exchange signal.
```python
from pydantic_ai.realtime import RealtimeTurnCompleteEvent
from pydantic_ai.realtime.openai import OpenAIRealtimeModel, OpenAIRealtimeModelSettings

ptt = OpenAIRealtimeModel('gpt-realtime-2.1', settings=OpenAIRealtimeModelSettings(turn_detection=False))
async def turn(session):
    await session.send('Hello')              # a text turn already requests a reply
    async for ev in session:
        if isinstance(ev, RealtimeTurnCompleteEvent):
            break
```
**Gotchas:**
- Don't follow `send()` with `create_response()`; the model answers twice. `respond=False` adds context without a reply.
- **While muted under VAD, keep sending zero PCM frames.** Mute the mic until the greeting has played, because echo
  cancels it.
- Branch on profile flags (`supports_manual_turn_control`, `supports_interruption`).
- Gemini, GPT-Live and ElevenLabs Agents have no manual turns.

**Doc:** `docs/realtime/audio.md`, `turns.md`, `events.md`

### 2.21 Realtime tools
**What:** agent tools run concurrently on your backend, with the same validation, retries and hooks as a text run.
Native tools come from `WebSearch()`, `WebFetch()` or `NativeTool(...)`.
```python
from pydantic_ai import Agent, RunContext

supervisor = Agent('openai:gpt-6.1-sol')
voice = Agent(instructions='Use `consult` for hard questions; call `hang_up` on goodbye.')

@voice.tool_plain
async def consult(question: str) -> str:            # delegate hard/structured work
    return (await supervisor.run(question)).output

@voice.tool
async def hang_up(ctx: RunContext) -> None:
    assert ctx.realtime_session is not None
    await ctx.realtime_session.hang_up()
```
**Gotchas:**
- **Approval-gated tools need a `HandleDeferredToolCalls(handler=...)` capability**, since there's no pausing.
  Without one they're always refused.
- A forcing `tool_choice` raises; restrict tools with `ToolOrOutput(function_tools=[...])` instead.
- Async tool calls:
  - always on for OpenAI, Azure and xAI;
  - opt-in on Gemini native-audio via `RealtimeModelSettings(async_tool_calls=True)`.

**Doc:** `docs/realtime/tools.md`

### 2.22 Realtime history, lifecycle, observability
```python
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

voice = Agent(instructions='Helpful voice assistant.')
notes = Agent('openai:gpt-6.1-sol', instructions='Summarize as bullets.')

async def main(prior=()):
    async with voice.realtime('openai:gpt-realtime-2.1', message_history=prior,
                              usage_limits=UsageLimits(total_tokens_limit=100_000),
                              model_settings={'reconnect': {'max_attempts': 5}}).session() as s:
        ...
    print((await notes.run('Summarize the call.', message_history=s.all_messages())).output)
```
**Gotchas:**
- Seeded history is trusted, so run client history through `sanitize_messages` first.
- Without a `reconnect` policy, a dropped connection raises `RealtimeError`.
- Reconnects can't move between processes.
- `handshake_timeout` defaults to 30 s.
- Use a watchdog that calls `close()` to cap call length.
- GPT-Live bills per second.
- Wrap the session in `logfire.span()` to include the handshake in traces.

**Doc:** `docs/realtime/history.md`, `lifecycle.md`, `observability.md`, `troubleshooting.md`

### 2.23 Realtime providers
| Provider | Model string → class | Extra | Notes |
|---|---|---|---|
| OpenAI gpt-realtime | `openai:gpt-realtime[-2.1]` → `OpenAIRealtimeModel` | `openai-realtime` | WebRTC, images, manual turns |
| OpenAI GPT-Live | `openai:gpt-live-1[+<backend>]` → `OpenAILiveModel` | `openai-realtime` | Delegates to a backend text model; owns turn-taking; per-second billing |
| Azure / Voice Live | `azure:<deployment>` → `AzureRealtimeModel` | `openai-realtime` | Pass `profile=` when the deployment name hides the model |
| Gemini Live | `google:gemini-3.8-live`, Vertex `google-cloud:gemini-live-2.5-flash` | `google-realtime` | No WebRTC; session resumption |
| xAI | `xai:grok-voice-latest` | `xai-realtime` | Audio only |
| ElevenLabs | `elevenlabs:eleven_realtime_v1_mini`, `elevenlabs-agents:<agent_id>` | `elevenlabs-realtime` / `elevenlabs-agents-realtime` | No images or async tools; Agents can't reconnect |

**Doc:** `docs/realtime/{openai,azure,gemini,xai,elevenlabs}.md`

### 2.24 Realtime deployment
**What:** the agent always runs on your backend, in one of three topologies:
1. **Browser WebRTC + sideband** (OpenAI and Azure). Call `answer_webrtc_offer(sdp)`, then
   `realtime.session(provider_session=answer.session)`. Media goes from the browser straight to the provider.
2. **WebSocket relay** (every provider). Pipe `websocket.receive_bytes()` into `send_audio()`, and send
   `stream_audio()` back.
3. **SIP** through Twilio or similar. It isn't built in.

**Gotchas:**
- On a sideband, `close()` only detaches: the browser's call stays up **and billed** until you call `hang_up()`.
- The browser can read seeded history.
- A call is pinned to one process, so drain on deploy. Request-scoped Lambdas don't fit.

**Doc:** `docs/realtime/deployment.md`, `docs/examples/realtime-*.md`

## 3. Experiment ideas

1. **TestModel / FunctionModel, no key.**
   - Run `Agent('test')` with two tools and print `all_messages()`.
   - Try `agent.override(model=TestModel(custom_output_text='hi'))`.
   - Use a `FunctionModel` that prints `info.model_settings` to watch model, agent and run settings merge.
2. **Local Ollama.**
   - Run `ollama pull qwen3`, then `OLLAMA_BASE_URL=http://localhost:11434/v1`.
   - Compare `output_type=NativeOutput(City)` with the default tool output.
   - Diff `model.profile` against an `OpenAICompatibleProvider` pointed at the same server.
3. **Fallback with no keys.**
   - Build `FallbackModel(FunctionModel(truncated), FunctionModel(complete), fallback_on=OutputTokenLimitExceeded)`.
   - Inspect `failed_attempts` and `usage`.
   - Compare with `ModelFallback` defaults.
4. **Error-policy drill.** Unit-test a `should_retry()` with
   `ModelHTTPError.for_category(ModelRateLimitError, status_code=429, model_name='x')`.
5. **Free web UI.**
   - Serve `Agent('test').to_web()` with uvicorn. TestModel streams; FunctionModel needs a `stream_function`.
   - Add a `requires_approval=True` tool and click approve or deny.
6. **Adapter smoke test.**
   - Serve FastAPI with `VercelAIAdapter.dispatch_request(..., sdk_version=6)` on a TestModel agent.
   - `curl -N` it with `content-type: application/json` and read the SSE.
   - Drop the header to see the 415.
   - Repeat with `AGUIAdapter` and `StateDeps`.
7. **Server-side history.** Add `manage_message_history='server'` and an `on_complete` dict store, then forge an
   earlier assistant turn and confirm it's ignored.
8. **Local decision model.**
   - Needs Ollama ≥0.35: `ollama pull nimble`, then `SYSTEM_ONE_BASE_URL=http://localhost:11434` (no `/v1`).
   - Run `Agent('system-one:nimble', output_type=Literal['billing','bug','account'], instructions='Which label?')`.
   - Print `provider_details`.
9. **clai tour.** Try `clai -m ollama:qwen3`, `clai --agent mod:agent`, `/usage --json`, then `--mcp-config` with a
   stdio MCP server.
10. **Realtime text-to-voice** (OpenAI or Gemini key).
    - Follow `docs/examples/realtime-text-to-audio.md`: save `stream_audio()` to a WAV.
    - Hand `session.all_messages()` to a summarizer agent.

## 4. Key takeaways

- **One string picks everything.** `'<provider>:<model>'` chooses class, provider and profile. Instantiate classes only
  for custom auth or endpoints (`provider=`) or request shaping (`profile=`). **`openai:` = Responses API**;
  `openai-chat:` = Chat Completions.
- **Any OpenAI-compatible server works.** Ollama, vLLM, LiteLLM and OpenRouter run through `OpenAIChatModel` plus a
  named provider, or `OpenAICompatibleProvider`. Fix quirks with `OpenAIModelProfile`.
- **Settings stack** model < agent < capability < run, and `thinking` is the portable reasoning knob.
- **Use `ModelFallback` inside agents.** `FallbackModel` is for direct calls. Set `max_retries=0` for fast failover.
- **Three names that mislead.** `{{ openai:medium }}` is a docs-only price-tier alias. `KnownModelName` is only
  autocomplete. "TypeSafe" is a decision-model vendor.
- **Interfaces are thin.**
  - `clai`/`to_cli_sync` for the terminal, `to_web()` for dev.
  - `AGUIAdapter`/`VercelAIAdapter` for production; `to_ag_ui()` is gone.
  - Treat adapter input as untrusted and keep history server-side.
- **Realtime voice is the same agent.** `agent.realtime(model).session()` keeps tools, deps, history and limits, with
  PCM16 at the profile's rates. `RealtimeTurnCompleteEvent` marks turn boundaries, `HandleDeferredToolCalls` handles
  approvals, and structured output comes from delegating to a text agent.
