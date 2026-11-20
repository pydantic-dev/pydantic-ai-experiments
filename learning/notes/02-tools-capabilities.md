# 02 — Tools, Toolsets, MCP & Capabilities (Pydantic AI v2.71)

Source: the local clone's docs. Signatures marked "(verified)" were checked against `pydantic_ai_slim/`.

Snippets use `'test'` (the offline `TestModel`) where possible. Real model strings come from `docs/model_aliases/aliases.json`, e.g. `anthropic:claude-sonnet-5-5` and `openai:gpt-6.1-sol`. In v2, `openai:` is the **Responses** API; use `openai-chat:` for Chat Completions.

## 1. Mental model

- **Tool.** A Python function the model may call. Pydantic AI builds its schema from the signature and docstring, and validates the model's arguments with Pydantic. Async tools run on the event loop; sync tools run in a thread.
- **Toolset.** A collection of tools behind `get_tools`/`call_tool`, and every tool source is one: `@agent.tool` functions sit in an internal `FunctionToolset`, an MCP server is an `MCPToolset`, frontend tools are an `ExternalToolset`. Wrappers compose them (`.prefixed()`, `.filtered()`, `.renamed()`, `.prepared()`, `.approval_required()`, `WrapperToolset`), and each run merges them all into one `CombinedToolset`.
- **Native tool.** Executed by the *provider*: web search, code execution, image generation, provider-side MCP. These appear as `NativeToolCallPart`s.
- **MCP.** Shows up three ways: as a client toolset (`MCPToolset`), as a native tool (`MCPServerTool`), and as the recommended `MCP` capability, which chooses between them.
- **Capability.** An `AbstractCapability` is v2's main extension unit. It bundles any of a toolset, native tools, instructions, model settings, model selection, and lifecycle hooks. Old `Agent` kwargs (`builtin_tools=`, `prepare_tools=`, `history_processors=`, `instrument=`) are now capabilities, and they nest like middleware: the first one listed is outermost.

Layering: **function → `Tool` → toolset → wrappers → capability → agent**.

> **v2 traps** (`changelog.md`, `migration.md`):
> - `MCPServerStdio`/`SSE`/`StreamableHTTP` were replaced by `MCPToolset`, and importing the old names raises `ImportError`.
> - `builtin_tools` became `capabilities=[NativeTool(...)]`.
> - `DeferredToolCalls` became `DeferredToolRequests`, and `DeferredToolset` became `ExternalToolset`.
> - `FunctionToolset.tool()` now requires a `RunContext` first parameter.
> - `pydantic_ai.ext.aci` was removed.

## 2. Features

### 2.1 `@agent.tool` vs `@agent.tool_plain` vs `tools=[...]`
**What it is.** `@agent.tool` functions take `RunContext[Deps]` as their first parameter, and `@agent.tool_plain` functions take none. `Agent(tools=[fn, Tool(fn)])` inspects the signature to tell which.
**Why/when.** Use `tool` to reach deps, `ctx.retry`, `ctx.tool_call_id` or `ctx.enqueue()`. Use `tool_plain` for pure functions.
**Minimal example**
```python
import random
from pydantic_ai import Agent, RunContext

agent = Agent('test', deps_type=str)

@agent.tool_plain
def roll_dice() -> str:
    """Roll a six-sided die and return the result."""
    return str(random.randint(1, 6))

@agent.tool
def get_player_name(ctx: RunContext[str]) -> str:
    """Get the player's name."""
    return ctx.deps
print(agent.run_sync('My guess is 4', deps='Anne').output)  # TestModel calls every tool
```
**Gotchas.**
- The decorator takes `retries=`, but `Tool()` takes `max_retries=` (verified).
- Sync tools run in threads, so `ContextVar` writes don't propagate. Prefer `async def`.

**Doc:** `docs/tools.md`

### 2.2 Schema & docstring extraction
**What it is.** Every parameter except `RunContext` goes into the schema. Griffe turns Google, NumPy and Sphinx docstrings into the tool description and parameter descriptions.
**Why/when.** You get good schemas for free. `require_parameter_descriptions=True` enforces that every parameter is documented.
**Minimal example**
```python
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
agent = Agent()

@agent.tool_plain(docstring_format='google', require_parameter_descriptions=True)
def foobar(a: int, b: str) -> str:
    """Get me foobar.

    Args:
        a: apple pie
        b: banana cake
    """
    return f'{a} {b}'
tm = TestModel(); agent.run_sync('hi', model=tm)
print(tm.last_model_request_parameters.function_tools[0].parameters_json_schema)
```
**Gotchas.**
- Only four docstring parts are sent: the description, `Args`, the first `Returns` entry, and `Note:`/`Warning:`. `Raises:` and `Examples:` are dropped.
- A function with a single object parameter is flattened to that object's schema.
- Enum member docstrings need `UseEnumMemberDocstrings`.

**Doc:** `docs/tools.md#function-tools-and-schema`

### 2.3 `Tool`, `Tool.from_schema`, strict mode
**What it is.** `Tool(fn, takes_ctx=, max_retries=, name=, prepare=, strict=, requires_approval=, defer_loading=…)` is a reusable tool definition (verified). `Tool.from_schema(...)` wraps functions whose signatures can't produce a schema.
**Why/when.** Share tools across agents, or wrap SDK functions. This is also the replacement for the removed ACI integration.
**Minimal example**
```python
from pydantic_ai import Agent, Tool

def foobar(**kwargs) -> str:
    return kwargs['a'] + kwargs['b']

sum_tool = Tool.from_schema(
    function=foobar, name='sum', description='Sum two numbers.',
    json_schema={'type': 'object', 'additionalProperties': False,
                 'properties': {'a': {'type': 'integer'}, 'b': {'type': 'integer'}},
                 'required': ['a', 'b']},
    takes_ctx=False,
)
print(Agent('test', tools=[sum_tool]).run_sync('add').output)  # {"sum":0}
```
**Gotchas.**
- `from_schema` does not validate arguments.
- `strict=None` (the default) leaves the choice to the provider: OpenAI turns it on automatically, Gemini 2.5+ uses `VALIDATED`, and Anthropic/Bedrock only use it with `True`.
- Don't share one `Tool` instance across toolsets: it picks up their defaults (#12617).

**Doc:** `docs/tools-advanced.md#strict-mode`

### 2.4 Prepare functions (per-tool `prepare`, agent-wide `PrepareTools`)
**What it is.** A per-tool `prepare(ctx, tool_def)` returns a modified definition, or `None` to hide the tool, on each step. The agent-wide `PrepareTools(fn)` capability does the same over the whole list, with `fn(ctx, defs) -> defs`. `PrepareOutputTools` covers output tools.
**Why/when.** Gate tools by role or deps, rewrite descriptions, or make every tool strict.
**Minimal example**
```python
from dataclasses import replace
from pydantic_ai import Agent, RunContext, ToolDefinition
from pydantic_ai.capabilities import PrepareTools

async def only_if_42(ctx: RunContext[int], tool_def: ToolDefinition) -> ToolDefinition | None:
    return tool_def if ctx.deps == 42 else None

async def all_strict(ctx: RunContext[int], defs: list[ToolDefinition]) -> list[ToolDefinition]:
    return [replace(d, strict=True) for d in defs]

agent = Agent('test', deps_type=int, capabilities=[PrepareTools(all_strict)])

@agent.tool(prepare=only_if_42)
def hitchhiker(ctx: RunContext[int], answer: str) -> str:
    return f'{ctx.deps} {answer}'
```
**Gotchas.**
- **Never build a fresh `ToolDefinition`:** it resets `kind`, which silently drops `requires_approval`. Use `replace()` instead.
- An agent-wide prepare must return `[]`; returning `None` raises `TypeError` in v2.
- A hidden tool also can't be executed.

**Doc:** `docs/tools-advanced.md#tool-prepare`, `docs/capabilities/prepare-tools.md`

### 2.5 Rich returns & `ToolReturn`
**What it is.** A tool can return anything JSON-serializable, plus `ImageUrl`, `DocumentUrl` and `BinaryContent`. `ToolReturn(return_value, *, content=, metadata=, tools=)` (verified) splits the result into four parts:
- `return_value`: the tool result
- `content`: a separate user message
- `metadata`: app-only, never sent to the model
- `tools`: names of deferred tools to reveal

**Why/when.** Screenshots, audit data ("artifacts"), unlocking hidden tools.
**Minimal example**
```python
from pydantic_ai import Agent, BinaryContent, ToolReturn

agent = Agent('test')

@agent.tool_plain
def click_and_capture(x: int, y: int) -> ToolReturn:
    """Click at coordinates and show a screenshot."""
    shot = BinaryContent(data=b'\x89PNG', media_type='image/png')
    return ToolReturn(
        return_value=f'Clicked at ({x}, {y})',  # the tool result
        content=['After:', shot],              # separate user message
        metadata={'coords': (x, y)},           # app-only
    )
```
**Gotchas.**
- A returned file rides inside the tool result on Anthropic, OpenAI Responses and Gemini 3. Elsewhere it goes on the user channel in `<pyai:tool_result>` framing, or becomes a note if the model can't read it.
- Files in `content` are always sent and can fail the request.

**Doc:** `docs/tools-advanced.md#advanced-tool-returns`

### 2.6 Retries, failures, timeouts, `args_validator`
**What it is.** There are four ways a tool can fail:
- **Validation error or `ModelRetry`:** sends a retry prompt and consumes the tool's retry budget.
- **`ToolFailed`:** reports "done, but failed" without consuming budget.
- **Any other exception:** aborts the run.
- **`args_validator(ctx, <params>)`:** runs after schema validation, before execution or approval.

**Why/when.** Use `ModelRetry` for args the model can fix, `ToolFailed` for a definitive 404, and validators for business rules you want checked before a human is asked.
**Minimal example**
```python
from pathlib import Path
from pydantic_ai import Agent, ModelRetry, ToolFailed

agent = Agent('test', retries={'tools': 3}, tool_timeout=30)

@agent.tool_plain(retries=5, timeout=5)
def read_file(path: str) -> str:
    if '..' in path:
        raise ModelRetry('Use a path inside the workspace, without "..".')
    p = Path(path)
    if not p.is_file():
        raise ToolFailed(f'File not found: {path}')  # no retry budget consumed
    return p.read_text()
```
**Gotchas.**
- **Retry budget precedence:** per-tool → toolset → `override()` → `run(retries=)` → `Agent(retries=)` → 1. A bare `int` sets both the tool and output budgets.
- **Exhausted budget:** raises `UnexpectedModelBehavior`. Since `ToolFailed` doesn't consume budget, cap repeated failures with `UsageLimits(request_limit=)`.
- **Timeouts:** enforced only by `FunctionToolset`.

**Doc:** `docs/tools-advanced.md#tool-retries`

### 2.7 Parallelism & `tool_choice`
**What it is.** Calls from a single response run concurrently:
- `sequential=True` turns a tool into a barrier.
- `parallel_tool_call_execution_mode('sequential')` serializes everything.
- `UseThreadExecutor` bounds the threads used by sync tools.

The `tool_choice` setting takes `'auto'`, `'none'`, `'required'`, a list of tool names, or `ToolOrOutput(function_tools=[...])`.
**Why/when.** Serialize writes, keep server threads bounded, force or forbid tool use.
**Minimal example**
```python
from concurrent.futures import ThreadPoolExecutor
from pydantic_ai import Agent
from pydantic_ai.capabilities import UseThreadExecutor
from pydantic_ai.settings import ToolOrOutput

agent = Agent('test', capabilities=[UseThreadExecutor(ThreadPoolExecutor(max_workers=16))])

@agent.tool_plain(sequential=True)
def write_to_database(record: str) -> str:
    return 'written'

agent.run_sync('hi', model_settings={'tool_choice': ToolOrOutput(function_tools=['write_to_database'])})
with agent.parallel_tool_call_execution_mode('sequential'):
    agent.run_sync('store it')
```
**Gotchas.**
- A static `'required'`, or a list with no output tool in it, raises `UserError` because the run could never end. Change it per step with a callable returned from a capability's `get_model_settings()`.
- Anthropic can't force a tool while thinking is on.

**Doc:** `docs/tools-advanced.md#tool-choice`

### 2.8 Tool search (deferred tool loading)
**What it is.** `defer_loading=True` on a tool, a `FunctionToolset`, or via `.defer_loading()` hides tools until the model searches for them. `ToolSearch(tools='all'|[names]|{meta}|fn)` selects them in one place. The auto-injected `ToolSearch` searches natively on Anthropic 4.5+ and OpenAI Responses GPT-5.4+, and falls back to a local `search_tools` tool elsewhere.
**Why/when.** More than ~10 tools, more than ~10k tokens of definitions, or many MCP servers. Keep hot tools eager.
**Minimal example**
```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import ToolSearch, keywords_search

def search(ctx, queries, tools) -> list[str]:
    exact = [t.name for t in tools if t.name in queries]
    return exact or keywords_search(ctx, queries, tools)

agent = Agent('anthropic:claude-sonnet-5-5', capabilities=[ToolSearch(strategy=search)])

@agent.tool_plain(defer_loading=True)
def mortgage_calculator(principal: float, rate: float, years: int) -> str:
    """Calculate monthly mortgage payment for a home loan."""
    return '...'
```
**Gotchas.**
- A bare `ToolSearch()` defers nothing, and deferring doesn't register new tools: every tool must still be declared.
- The local fallback breaks the prompt cache on each discovery, and always does on Gemini.
- Discoveries live in history as `ToolAvailabilityDeltaPart`s.

**Doc:** `docs/tools-advanced.md#tool-search`

### 2.9 Typed tool parts (one-liner)
`ToolKind('ns', 'name', args=, content=)` combined with `class P(ToolCallPart[Args], kind=k)` gives you typed parts. Hooks can then match them with `isinstance`, and that survives prefixing and renaming. See also `unless_tool_kind` and `ctx.tool_name_for_kind()`. **Doc:** `docs/tools-advanced.md#typed-tool-parts`

### 2.10 `FunctionToolset` & where toolsets go
**What it is.** Toolsets can be supplied through `Agent(toolsets=)`, `run(toolsets=)` (added to the agent's), `@agent.toolset` (dynamic), or `agent.override(toolsets=)` (replaces all). `FunctionToolset(tools, instructions=, max_retries=, requires_approval=, defer_loading=, id=)` holds local functions, and its instructions are appended after the agent's.
**Why/when.** Reusable tool bundles you can swap out in tests.
**Minimal example**
```python
from pydantic_ai import Agent, FunctionToolset, RunContext

weather = FunctionToolset(instructions='Use weather tools for forecasts.')

@weather.tool_plain
def forecast(city: str) -> str:
    """Get weather forecast."""
    return 'Sunny'

@weather.tool  # v2: FunctionToolset.tool REQUIRES RunContext first
def conditions(ctx: RunContext, city: str) -> str:
    return "It's raining" if ctx.run_step % 2 else "It's sunny"

weather.add_function(lambda: '12:00', name='now')
agent = Agent('test', toolsets=[weather])
```
**Gotchas.**
- Duplicate tool names across toolsets raise an error.
- `add_function()` called from inside a tool takes effect on the next step.

**Doc:** `docs/toolsets.md`

### 2.11 Composition: Combined / Filtered / Prefixed / Renamed / Prepared / ApprovalRequired
**What it is.** Fluent wrappers on every toolset (verified):
- `CombinedToolset([...])`
- `.filtered(fn(ctx, td) -> bool)`
- `.prefixed('p')`
- `.renamed({'new': 'old'})`
- `.prepared(fn(ctx, defs))`, which can't add or rename tools
- `.approval_required(fn(ctx, td, args) -> bool)`
- `.defer_loading()`, `.include_return_schemas()`, `.with_metadata(**kv)`

**Why/when.** Namespace MCP servers, hide tools by role, put approval in front of third-party tools.
**Minimal example**
```python
from pydantic_ai import Agent, CombinedToolset, DeferredToolRequests, FunctionToolset

def temperature_celsius(city: str) -> float: return 21.0
def temperature_fahrenheit(city: str) -> float: return 69.8
def now() -> str: return '12:00'

weather, clock = FunctionToolset([temperature_celsius, temperature_fahrenheit]), FunctionToolset([now])
toolset = (
    CombinedToolset([weather.prefixed('weather'), clock.prefixed('clock')])
    .filtered(lambda ctx, td: 'fahrenheit' not in td.name)
    .renamed({'current_time': 'clock_now'})  # new_name: old_name
    .approval_required(lambda ctx, td, args: td.name.startswith('weather_'))
)
agent = Agent('test', toolsets=[toolset], output_type=[str, DeferredToolRequests])
```
**Gotchas.**
- `renamed` maps **new → old**.
- `ApprovalRequiredToolset` checks at call time, so a sloppy `prepare` can't strip it the way it can strip `requires_approval=True`.

**Doc:** `docs/toolsets.md#toolset-composition`

### 2.12 `WrapperToolset`
**What it is.** A toolset that delegates to another. Subclass it and override `call_tool(name, tool_args, ctx, tool)` or `get_tools`.
**Why/when.** Logging, caching or redaction for one toolset. For the whole agent, use a capability hook instead.
**Minimal example**
```python
from typing import Any
from pydantic_ai import Agent, FunctionToolset, RunContext, ToolsetTool, WrapperToolset

class LoggingToolset(WrapperToolset):
    async def call_tool(self, name: str, tool_args: dict[str, Any], ctx: RunContext, tool: ToolsetTool) -> Any:
        print(f'-> {name}({tool_args})')
        return await super().call_tool(name, tool_args, ctx, tool)

def ping() -> str: return 'pong'
Agent('test', toolsets=[LoggingToolset(FunctionToolset([ping]))]).run_sync('go')
```
**Gotchas.**
- MCP App tools return a `ToolReturn` with `metadata['mcp_app']`. Edit `return_value`, not the whole object.

**Doc:** `docs/toolsets.md#changing-tool-execution`

### 2.13 `ExternalToolset` (frontend / external execution)
**What it is.** A toolset built from raw `ToolDefinition`s that is never executed in-process. Its calls end the run as `DeferredToolRequests.calls`.
**Why/when.** Browser and UI tools, and work done by another service. The AG-UI and Vercel AI adapters use it.
**Minimal example**
```python
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, ExternalToolset, ToolDefinition

frontend = ExternalToolset([ToolDefinition(
    name='get_preferred_language', description="User's browser language",
    parameters_json_schema={'type': 'object', 'properties': {'default_language': {'type': 'string'}}},
)])
agent = Agent('anthropic:claude-sonnet-5-5', toolsets=[frontend], output_type=[str, DeferredToolRequests])

r1 = agent.run_sync('Greet me in my language')
if isinstance(r1.output, DeferredToolRequests):
    results = DeferredToolResults(calls={c.tool_call_id: 'es-MX' for c in r1.output.calls})
    r2 = agent.run_sync(message_history=r1.all_messages(), deferred_tool_results=results)
```
**Gotchas.**
- A run-time `output_type=` *replaces* the agent's, so pass `[agent.output_type, DeferredToolRequests]`.
- A result may be a value, `ToolReturn`, `ModelRetry` or `ToolFailed`.

**Doc:** `docs/toolsets.md#external-toolset`

### 2.14 Dynamic & custom toolsets
**What it is.** A dynamic toolset is a function `(ctx) -> toolset | None`, decorated with `@agent.toolset(per_run_step=True, id=None)` (verified). A custom toolset subclasses `AbstractToolset` and implements `get_tools(ctx) -> dict[str, ToolsetTool]` and `call_tool`. Optional overrides are `get_instructions`, `for_run`, `for_run_step` and `__aenter__`.
**Why/when.** Per-user MCP servers or credentials, or a proprietary tool registry.
**Minimal example**
```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext
from pydantic_ai.mcp import MCPToolset

@dataclass
class UserDeps:
    mcp_url: str

agent = Agent('anthropic:claude-sonnet-5-5', deps_type=UserDeps)

@agent.toolset(per_run_step=False)
def user_mcp(ctx: RunContext[UserDeps]) -> MCPToolset:
    return MCPToolset(ctx.deps.mcp_url, id='user-mcp')
```
**Gotchas.**
- The docs have no full custom-toolset example; read `toolsets/external.py`.
- If you also need hooks or settings, write a capability instead.

**Doc:** `docs/toolsets.md#dynamically-building-a-toolset`

### 2.15 Deferred tools: approval (HITL) & external execution
**What it is.** Three things end a run with a `DeferredToolRequests` output (fields `approvals`, `calls`, `metadata`, `validated_args`):
- `requires_approval=True` on the tool
- `raise ApprovalRequired(metadata=)` inside it, guarded by `not ctx.tool_call_approved`
- `raise CallDeferred(metadata=)` for external execution; `kind='question'` asks the user

To resume, run again with `message_history=` and `DeferredToolResults(approvals={id: bool|ToolApproved(override_args=)|ToolDenied(msg)}, calls={id: value|ToolReturn|ModelRetry|ToolFailed})`.
**Why/when.** Destructive actions, protected resources, long jobs, work done by another service.
**Minimal example**
```python
from pydantic_ai import Agent, CallDeferred, DeferredToolRequests, ToolDenied

agent = Agent('anthropic:claude-sonnet-5-5', output_type=[str, DeferredToolRequests])

@agent.tool_plain(requires_approval=True)
def delete_file(path: str) -> str:
    return f'deleted {path}'
@agent.tool_plain
async def run_report(name: str) -> str:
    raise CallDeferred(metadata={'job': name})  # executed elsewhere
r = agent.run_sync('Delete tmp.txt and run the sales report')
req = r.output  # DeferredToolRequests(approvals=[...], calls=[...])
res = req.build_results(approvals={c.tool_call_id: ToolDenied('No deletes') for c in req.approvals},
                        calls={c.tool_call_id: 'report done' for c in req.calls})
r = agent.run_sync(message_history=r.all_messages(), deferred_tool_results=res)
```
**Gotchas.**
- **Approval ≠ authorization.** UI clients submit approvals themselves.
- Show approvers `validated_args[id]`. `run_stream()` doesn't fill it for the call it ends on (#13690).
- To persist across processes, store `result.conversation` via `ConversationTypeAdapter`, then resume with `conversation=`.

**Doc:** `docs/deferred-tools.md`

### 2.16 Inline resolution: `HandleDeferredToolCalls`
**What it is.** A capability that continues the *same* run. Its `handler(ctx, requests)` returns `DeferredToolResults`, or `None` to decline. The 3-argument form `handler(ctx, requests, token)` can instead hand a resume token to an approver, and the run waits for `resolve_external_event(token, answer)` from `pydantic_ai.external_events`. On AWS Lambda durable functions, that wait is durable.
**Why/when.** Policy auto-approval, or approval UIs in the same process.
**Minimal example**
```python
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults, RunContext
from pydantic_ai.capabilities import HandleDeferredToolCalls

def refund_policy(ctx: RunContext, requests: DeferredToolRequests) -> DeferredToolResults:
    return requests.build_results(
        approvals={c.tool_call_id: requests.validated_args[c.tool_call_id]['amount'] <= 100
                   for c in requests.approvals},
    )

agent = Agent('anthropic:claude-sonnet-5-5', capabilities=[HandleDeferredToolCalls(refund_policy)])

@agent.tool_plain(requires_approval=True)
def issue_refund(order_id: str, amount: int) -> str:
    return f'Refunded ${amount} for order {order_id}'
```
**Gotchas.**
- Fields (verified): `handler`, `timeout`.
- To decline, a token handler returns `build_results()`; returning `None` makes the run wait for the token.
- Unresolved calls bubble up as `DeferredToolRequests`.

**Doc:** `docs/capabilities/handle-deferred-tool-calls.md`

### 2.17 Common tools (run locally, work with any model)
**What it is.** Factories in `pydantic_ai.common_tools` (verified):
- `duckduckgo_search_tool(max_results=)` (extra: `[duckduckgo]`)
- `tavily_search_tool(api_key, ...)` (extra: `[tavily]`); parameters you fix are hidden from the LLM
- `web_fetch_tool(max_content_length=50_000, allowed_domains=, headers=)` (extra: `[web-fetch]`); converts pages to markdown, with SSRF protection

**Why/when.** Search and fetch for models without native tools.
**Minimal example**
```python
from pydantic_ai import Agent
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool
from pydantic_ai.common_tools.web_fetch import web_fetch_tool

agent = Agent(
    'anthropic:claude-sonnet-5-5',
    tools=[duckduckgo_search_tool(max_results=5), web_fetch_tool(allowed_domains=['pydantic.dev'])],
)
```
**Gotchas.**
- `headers=` go to *any* URL the model picks.
- The Exa tools are deprecated; use the Harness `ExaSearch` instead.
- Usually you'd reach these through `WebSearch`/`WebFetch(local=…)`.

**Doc:** `docs/common-tools.md`

### 2.18 Native (provider-executed) tools
**What it is.** `WebSearchTool`, `WebFetchTool`, `CodeExecutionTool`, `ImageGenerationTool`, `XSearchTool` (xAI), `MemoryTool` (Anthropic), `MCPServerTool`, `FileSearchTool` (managed RAG) and `AdvisorTool`. Register one as `capabilities=[NativeTool(tool)]`, or pass a factory `NativeTool(fn)` that returns a tool or `None` per request.
**Why/when.** Search and sandboxes with no infrastructure of your own, plus provider-side citations.
**Minimal example**
```python
from pydantic_ai import Agent, CodeExecutionTool, RunContext, WebSearchTool
from pydantic_ai.capabilities import NativeTool

async def search_for_user(ctx: RunContext[dict]) -> WebSearchTool | None:
    city = ctx.deps.get('city')
    return WebSearchTool(user_location={'city': city}, max_uses=5) if city else None

agent = Agent('anthropic:claude-sonnet-5-5', deps_type=dict,
              capabilities=[NativeTool(search_for_user), NativeTool(CodeExecutionTool())])
result = agent.run_sync('Weather here, and 15!?', deps={'city': 'London'})
print(result.response.native_tool_calls)  # [(NativeToolCallPart, NativeToolReturnPart), ...]
```
**Gotchas.**
- An unsupported provider raises `UserError`.
- Restricting parameters (domains, `max_uses`) on a model that can't enforce them make the tool unsupported. Gemini enforces none of them.
- `provider_settings` is keyed by **model class**.
- On OpenAI, native tools need the Responses API.

**Doc:** `docs/native-tools.md`

### 2.19 Third-party tools
**What it is.** `tool_from_langchain(t)` and `LangChainToolset(tools)` live in `pydantic_ai.ext.langchain`. Community packages are listed in `docs/capabilities/third-party.md`.
**Why/when.** Reuse the LangChain tool catalog.
**Minimal example**
```python
from langchain_community.tools import DuckDuckGoSearchRun
from pydantic_ai import Agent
from pydantic_ai.ext.langchain import tool_from_langchain

agent = Agent('google:gemini-3.8-flash', tools=[tool_from_langchain(DuckDuckGoSearchRun())])
```
**Gotchas.**
- Arguments are **not validated**.
- **ACI was removed in v2.** Wrap the ACI SDK with `Tool.from_schema` instead.

**Doc:** `docs/third-party-tools.md`

### 2.20 MCP client: `MCPToolset`
**What it is.** A FastMCP 3/4-based toolset. Its first argument can be a URL (Streamable HTTP, or SSE if the path ends in `/sse`), a `.py`/`.js` script run over stdio, a FastMCP transport or `Client`, or an in-process `FastMCP` server. Keyword arguments (verified) include `id`, `tool_error_behavior` (`'retry'|'failed'|'error'`), `process_tool_call`, `cache_tools`, `include_instructions=False`, `sampling_model`, `elicitation_handler`, `auth` and `http_client`. `load_mcp_toolsets('mcp_config.json')` reads Claude-Desktop-style config files.
**Why/when.** Use it when you need lifecycle control or a server shared between agents. Otherwise use the `MCP` capability (§2.24).
**Minimal example**
```python
from fastmcp import FastMCP
from fastmcp.client.transports import StdioTransport
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset

server = FastMCP('math')

@server.tool()
async def add(a: int, b: int) -> int:
    return a + b

in_proc = MCPToolset(server, id='math')  # no network
stdio = MCPToolset(StdioTransport(command='python', args=['mcp_server.py'])).prefixed('local')
remote = MCPToolset('http://localhost:8000/mcp', tool_error_behavior='failed')
agent = Agent('anthropic:claude-sonnet-5-5', toolsets=[in_proc, stdio, remote])
```
**Gotchas.**
- `async with agent:` keeps connections open between runs.
- Server instructions are off on `MCPToolset` but on in `MCP`, and they carry operator authority.
- For per-user credentials pass `auth=fn(ctx)`, which gives each run its own session.
- Config files can spawn arbitrary commands.
- FastMCP 4 uses `httpx2`.

**Doc:** `docs/mcp/client.md`

### 2.21 MCP sampling & elicitation
**What it is.** Sampling lets an MCP server use the client's LLM: set `MCPToolset(sampling_model=)` or call `agent.set_mcp_sampling_model()` (verified). Elicitation lets the server ask the user for structured input: pass `elicitation_handler=fn(message, response_type, params, context) -> ElicitResult`.
**Why/when.** Servers that have no LLM keys of their own, and interactive flows.
**Minimal example**
```python
from fastmcp.client.elicitation import ElicitResult
from fastmcp.client.transports import StdioTransport
from pydantic_ai import Agent
from pydantic_ai.mcp import MCPToolset

async def handle_elicitation(message, response_type, params, context) -> ElicitResult:
    return ElicitResult(action='accept', content={'restaurant': 'Luigi', 'party_size': 2, 'date': '01-12-2026'})

toolset = MCPToolset(StdioTransport(command='python', args=['restaurant_server.py']),
                     elicitation_handler=handle_elicitation)
agent = Agent('anthropic:claude-sonnet-5-5', toolsets=[toolset])
agent.set_mcp_sampling_model()  # server-side sampling now uses this agent's model
```
**Gotchas.**
- FastMCP 4 defaults to the 2026-07-28 protocol, which forbids *mid-tool-call* requests (`ctx.elicit`, `create_message`, `MCPSamplingModel`). They fail with `NoBackChannelError`. Fix it with FastMCP 3 or `Client(..., mode='legacy')`.

**Doc:** `docs/mcp/client.md#mcp-sampling`

### 2.22 MCP server (an agent inside a FastMCP tool)
**What it is.** An agent that runs inside an MCP tool. With `MCPSamplingModel(session=ctx.session)`, its LLM calls go back through the client.
**Why/when.** Expose an agent to Claude Desktop or Cursor without giving the server credentials.
**Minimal example**
```python
from fastmcp import Context, FastMCP
from pydantic_ai import Agent
from pydantic_ai.models.mcp_sampling import MCPSamplingModel

server = FastMCP('Pydantic AI Server')
poet_agent = Agent(instructions='always reply in rhyme')  # model supplied per run

@server.tool()
async def poet(ctx: Context, theme: str) -> str:
    """Poem generator"""
    r = await poet_agent.run(f'write a poem about {theme}', model=MCPSamplingModel(session=ctx.session))
    return r.output

if __name__ == '__main__':
    server.run()
```
**Gotchas.**
- The FastMCP 4 back-channel restriction from §2.21 applies.
- The `[mcp]` extra installs only the client; run `pip install fastmcp` for servers.

**Doc:** `docs/mcp/server.md`

### 2.23 Capabilities — the model
**What it is.** Pass `capabilities=[...]` to `Agent` or `run()`. A capability can contribute through `get_toolset`, `get_native_tools`, `get_instructions`, `get_model_settings`, `get_model`, `get_wrapper_toolset`, `get_wrapper_model` and hooks. Multiple capabilities merge into a `CombinedCapability`: configuration merges with later capabilities winning, `before_*` hooks run in list order, `after_*` hooks run in reverse, and `wrap_*` hooks nest with the first capability outermost. `Capability(...)` is the shorthand that needs no subclass. A function `(ctx) -> capability` is built per run.
**Why/when.** Memory, guardrails, cost tracking, approvals. Harness ships many more.
**Minimal example**
```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import Capability, Thinking, WebSearch

refunds = Capability(
    id='refunds',
    description='Use for refund eligibility and refund status.',
    instructions='Always confirm the order ID before issuing a refund.',
)

@refunds.tool_plain
def refund_status(order_id: str) -> str:
    """Look up the refund status for an order."""
    return f'Order {order_id}: refund issued on 2026-05-01.'

agent = Agent('anthropic:claude-sonnet-5-5', capabilities=[refunds, Thinking('high'), WebSearch(local='duckduckgo')])
```
**Gotchas.**
- Built-in capabilities have fixed ids (`'web_search'`, `'thinking'`…). Two on one agent merge; one passed to `run()` *replaces* the agent's.
- Base fields are `KW_ONLY` (verified), so `Thinking('high')` and `Caching('1h')` work positionally.
- Any `on_event` listener makes `run()` stream.

**Doc:** `docs/capabilities/overview.md`

### 2.24 Provider-adaptive: `WebSearch`, `WebFetch`, `ImageGeneration`, `XSearch`, `MCP`
**What it is.** These are `NativeOrLocalTool` subclasses: native where the model supports it, the `local=` fallback otherwise. `WebSearch()` and `WebFetch()` are native-only until you pass `local=`. `XSearch` falls back with `fallback_subagent_model='xai:…'`, and `ImageGeneration` with `fallback_image_model=`. `MCP` is the exception: **local by default**, with `native=True` to opt into the native version.
**Why/when.** Write the agent once and run it on any provider.
**Minimal example**
```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import MCP, WebFetch, WebSearch, XSearch
from pydantic_ai.native_tools import WebSearchTool

def docs_search(query: str) -> str:
    """Search pydantic.dev only."""
    return f'pydantic.dev results for {query}'

agent = Agent('openai:gpt-6.1-sol', capabilities=[
    WebSearch(native=WebSearchTool(allowed_domains=['pydantic.dev']), local=docs_search),
    WebFetch(allowed_domains=['pydantic.dev'], local=True),
    XSearch(fallback_subagent_model='xai:grok-4.7'),
    MCP('https://mcp.example.com/api', id='docs', tool_prefix=True, native=True),
])
```
**Gotchas.**
- Restrictions placed on `WebSearch` itself disable `local`; put them on the `native=` tool instead.
- `MCP`'s id defaults to the URL hostname, so two servers on one host need explicit ids.
- For per-user MCP credentials, pass `authorization_token=fn(ctx)`.

**Doc:** `docs/capabilities/overview.md#provider-adaptive-tools`, `mcp.md`

### 2.25 Remaining core capabilities (`docs/capabilities/*.md`)

| Capability | Usage | Gotcha |
|---|---|---|
| `Caching` | `Caching()`, `Caching('1h')`, `Caching(messages=False)` | Off by default. Anthropic caches nothing without it. Provider `*_cache*` settings override it. |
| `OpenAICompaction` / `AnthropicCompaction` | `OpenAICompaction(token_threshold=100_000)` (from `models.openai`) | Provider-only. Use `ProcessHistory` or Harness elsewhere. |
| `ModelFallback` | `ModelFallback('anthropic:…', fallback_on=..., sticky=False)` | Also falls back on refusals and truncation by default (unlike `FallbackModel`). |
| `RetryOnModelErrors` | `RetryOnModelErrors(max_attempts=3)` | Retries the same model before `ModelFallback` moves on. |
| `Thinking` | `Thinking('high')` or `model_settings={'thinking': 'high'}` | Effort is snapped per provider. Provider-specific settings win. |
| `PrefixTools` | `PrefixTools(MCP(...), prefix='a')` or `cap.prefix_tools('a')` | Only the wrapped capability's tools get the prefix. |
| `SetToolMetadata` / `IncludeToolReturnSchemas` | `SetToolMetadata(tools=['search'], sensitive=True)` | Toolset forms: `.with_metadata()` / `.include_return_schemas()`. |
| `ProcessHistory` | `ProcessHistory(fn)` (was `history_processors=`) | Its output *replaces* the history. |
| `ProcessEventStream` | `ProcessEventStream(async_fn)` | Forces streaming. |
| `ReinjectSystemPrompt` | `ReinjectSystemPrompt(replace_existing=True)` | UI adapters add it automatically. |
| `RaiseContentFilterError` | `RaiseContentFilterError()` | Raises even when partial text came back. |
| `SelectModel` / `ResolveModelId` | `SelectModel(fn)` / `ResolveModelId(fn)` | `override(model=)` beats them. No I/O under durable execution. |
| `Instrumentation` | `Instrumentation()` (was `instrument=`) | Alternatively, `Agent.instrument_all()`. |
| `FileUnderstanding` | `FileUnderstanding(fallback_subagent_model=...)` | Describes each unreadable file once per conversation. |
| `Hooks` | `hooks = Hooks(); @hooks.on.before_tool_execute(tools=['x'])` | See `docs/hooks.md`. Supports `ordering=` and `timeout=`. |
| `NativeTool`, `Toolset`, `UseThreadExecutor`, `PrepareTools`, `ToolSearch` | See §2.18, §2.14, §2.7, §2.4, §2.8 | |

### 2.26 On-demand (deferred) capabilities
**What it is.** A capability with `defer_loading=True` and a stable `id` collapses to a single catalog line. When the model calls the reserved `load_capability(id=)` tool, the capability's instructions (as a system message), tools, settings and hooks all go live. Code can do the same with `ctx.load_capability(cap)`.
**Why/when.** Multi-workflow agents, and Markdown "skills" whose tools stay hidden until the skill is loaded. Use tool search for flat catalogs instead.
**Minimal example**
```python
from pydantic_ai import Agent, FunctionToolset
from pydantic_ai.capabilities import Capability, CombinedCapability, WebFetch, WebSearch

release_tools = FunctionToolset()

@release_tools.tool_plain
def stage_release(version: str) -> str:
    """Build a release and stage it for verification."""
    return f'Release {version} staged.'

release = Capability(id='release', description='Cut and stage a release.', instructions='Verify first.',
                     toolsets=[release_tools], defer_loading=True)
web = CombinedCapability([WebSearch(), WebFetch()], id='web-research',
                         description='Up-to-date info from the web.', defer_loading=True)
agent = Agent('openai:gpt-6.1-sol', capabilities=[release, web])
```
**Gotchas.**
- Ids must be stable, because loads are rebuilt from history.
- Loading native tools breaks the prompt cache; loading instructions alone never does.
- Text from `get_instructions`/`get_description` gets operator authority.

**Doc:** `docs/capabilities/on-demand.md`

### 2.27 Writing a custom capability
**What it is.** Subclass `AbstractCapability[Deps]`:
- **Configuration:** `get_toolset`, `get_instructions`, `get_model_settings` (return a callable for per-step settings), `get_wrapper_toolset`, `get_wrapper_model`, `get_model`, `get_ordering`.
- **Binding:** `for_agent`, called synchronously at construction; `for_run(ctx)`, which must return a **fresh** instance.
- **Hooks:** `before_*`, `after_*`, `wrap_*(handler)` and `on_*_error` for run, node, model request, tool validate/execute and output. Plus `prepare_tools`, `wrap_run_event_stream`, `@on_event` and `handle_deferred_tool_calls`.

**Why/when.** Guardrails, PII redaction, logging middleware, routing.
**Minimal example**
```python
from dataclasses import dataclass
from typing import Any
from pydantic_ai import Agent, ModelRequestContext, RunContext
from pydantic_ai.capabilities import AbstractCapability
@dataclass
class AuditAndCount(AbstractCapability[Any]):
    count: int = 0
    async def for_run(self, ctx: RunContext[Any]) -> 'AuditAndCount':
        return AuditAndCount()  # per-run state isolation
    async def before_model_request(self, ctx: RunContext[Any], request_context: ModelRequestContext) -> ModelRequestContext:
        self.count += 1
        return request_context
    async def wrap_tool_execute(self, ctx, *, call, tool_def, args, handler) -> Any:
        print(f'tool {call.tool_name}({args})'); return await handler(args)
agent = Agent('test', capabilities=[AuditAndCount()])
```
**Gotchas.**
- Order: every wrap enters → `before_*` hooks in list order → core operation → `after_*` hooks in reverse → wraps exit.
- `SkipModelRequest`/`SkipToolExecution` short-circuit the operation. `RetryModelRequest(model?)` retries within the same step.
- Steer the model with `ctx.enqueue(...)`; appending to `request_context.messages` directly is deprecated.
- Coordinate with other capabilities through `CapabilityEvent`, `ctx.emit()` and `@on_event`.
- To use a capability in agent specs, implement `from_spec` and pass the class in `custom_capability_types=`.

**Doc:** `docs/capabilities/custom.md`, `docs/hooks.md`

## 3. Experiment ideas (increasing difficulty)

1. **Schema microscope.** Use `FunctionModel` to print the schemas of tools defined with a Google docstring, with a `BaseModel` parameter, and with a `UseEnumMemberDocstrings` enum.
2. **Retry lab.** Write one tool that raises `ModelRetry` twice and one that raises `ToolFailed`. Vary the retry settings, then compare `ToolReturnPart.outcome` for each.
3. **Toolset pipeline.** Create a tool-name clash and fix it with `.prefixed()`. Chain `.filtered().renamed().prepared()` and inspect `last_model_request_parameters`.
4. **HITL CLI.** Approve tool calls with `input()`, then resume the run. Next, switch to `HandleDeferredToolCalls`. Finally, persist the run with `ConversationTypeAdapter` and resume it from a separate process.
5. **Middleware capability.** Time model requests with `wrap_model_request`, log tool calls with `wrap_tool_execute`, and redact emails in `after_model_request`. Stack it with `Hooks()` and check the order hooks fire in.
6. **Local MCP.** Attach an in-process `FastMCP` server via `MCPToolset` and via `MCP(local=...)`. Compare `tool_error_behavior='retry'` with `'failed'`.
7. **Provider-adaptive agent.** Build an agent with `WebSearch(local='duckduckgo')`, `WebFetch(local=True)`, `Thinking()` and `Caching()`. Run it on three providers and compare `native_tool_calls` and `cache_read_tokens`.
8. **Tool search at scale.** Define 60 deferred tools and compare token usage against eager loading. Then add a custom `strategy=`.
9. **Skills.** Turn Markdown skills into `Capability(defer_loading=True)`. Use `FunctionModel` to verify the load sequence, then trigger loading yourself with `ctx.load_capability()`.
10. **MCP sampling (stretch).** Reproduce `NoBackChannelError` on FastMCP 4 and fix it with `mode='legacy'`. Then serve an agent via `MCPSamplingModel`.

## 4. Key takeaways

- **Everything is a toolset.** Agent tools, MCP servers and frontend tools share the same wrappers and merge into one `CombinedToolset`. Name clashes raise errors, so prefix early.
- **v2 moved config into `capabilities=[...]`.** Examples: `NativeTool`, `PrepareTools`, `ProcessHistory`, `Instrumentation`, `MCP`. Distrust v1 tutorials.
- **Three failure signals.** `ModelRetry` means "fix args" and uses the retry budget. `ToolFailed` means "done, failed" and doesn't. Anything else aborts the run.
- **Deferral resumes two ways.** Either stop-the-world (`DeferredToolRequests` → `DeferredToolResults`) or inline (`HandleDeferredToolCalls`). Approval is UX, not authorization.
- **Native vs local is decided per model** by the provider-adaptive capabilities. `MCP` is local-first, and `MCPToolset` ignores server instructions by default.
- **Cache economics shape the design.** Tool search, on-demand capabilities, `Caching()` and `on_change='append'` all keep the prompt prefix stable.
- **Capabilities are middleware.** The first one listed is outermost. Isolate per-run state with `for_run`.
- **Iterate offline** with `TestModel`/`FunctionModel` and `last_model_request_parameters`.
