# Pydantic AI: core agent features (v2.71, main)

**Sources:** the `docs/*.md` files in `/home/ubuntu/pydantic-dev/pydantic-ai-experiments`. I checked any API I wasn't sure of against `pydantic_ai_slim/pydantic_ai/`.

**Model names:** the docs write model names as aliases like `'{{ openai:medium }}'`. The file `docs/model_aliases/aliases.json` maps each alias to a real model:

| Alias | Real model |
|---|---|
| `openai:medium` | `openai:gpt-6.1-sol` |
| `anthropic:medium` | `anthropic:claude-sonnet-5-5` |
| `google:medium` | `google:gemini-3.8-flash` |
| `openai:embedding` | `text-embedding-3-small` |
| `openai:image` | `gpt-image-2.5-flare` |

The snippets below use real names, or `'test'`. `'test'` is the offline `TestModel`, which needs no API key.

## 1. Overview

**`Agent[DepsT, OutputT]`.** An agent is a reusable, typed container. It holds:
- a default model;
- instructions;
- tools and toolsets;
- an `output_type` and a `deps_type`;
- model settings;
- **capabilities**: reusable bundles of tools, hooks, instructions and settings.

In V2, most agent kwargs that existed in V1 became capabilities.

**A run.** Each call to `run`, `run_sync`, `run_stream`, `run_stream_events` or `iter` is one run. A run is a pydantic-graph loop: `UserPromptNode → ModelRequestNode → CallToolsNode → …`. It ends when the model produces something matching the output type. A usage limit, timeout or cancellation can also end it.

**`RunContext` (`ctx`).** Instructions, tools, output functions, validators and hooks all receive it. It carries your typed **deps** plus run state: `usage`, `usage_limits`, `retry`, `run_step`, `messages`, `deadline` and `partial_output`. It also offers `emit()`, `enqueue()` and `cancel()`.

**Output types.** The output type decides what ends a run and what `result.output` is. Options:
- plain text;
- Pydantic models and unions;
- output functions;
- marker classes: `ToolOutput`, `NativeOutput`, `PromptedOutput` and `TextOutput`;
- `BinaryImage`;
- pause outputs: `DeferredToolRequests` and `PendingModelResponse`.

**History.** Each run produces message history: `ModelRequest` and `ModelResponse` dataclasses. You can:
- serialize it;
- pass it back with `message_history=`;
- carry it as a `Conversation` with `conversation=`. A `Conversation` holds the messages, usage, conversation ID and any pending calls.

**Around the loop.** Retries, timeouts, cancellation, usage limits, hooks and persistence each have their own budget.

**Same model layer, no agent loop.** Direct model requests, `ImageGenerator`, `Embedder` and the batch APIs.

## 2. Features

### Install and model strings
- **What it is:** `pydantic-ai` is the full install. `pydantic-ai-slim[extras]` lets you install only what you need. Requires Python 3.11+.
- **When:** use slim installs in production. Use `Agent('test')` to learn with no API key.
- **Example:**

  ```bash
  uv add pydantic-ai          # or: uv add "pydantic-ai-slim[openai,anthropic,retries,spec]"
  ```
- **Gotchas:**
  - In V2, the `openai:` prefix means the **Responses API**. Use `openai-chat:` for Chat Completions.
  - A model string with no provider prefix raises `UserError`.
  - Bedrock, Groq, Mistral, xAI, Temporal, UI and spec support now need extras.
  - `docs/migration.md` lists the V1→V2 renames, for example `result_type`→`output_type`, `result.usage()`→`result.usage` and `OpenAIModel`→`OpenAIChatModel`.
- **Doc:** `docs/install.md`, `docs/migration.md`

### Agent basics and typing
- **What it is:** the `Agent(...)` kwargs, as defined in source:
  - `output_type`, `instructions`, `system_prompt`
  - `deps_type`, `name`, `description`
  - `model_settings`, `retries`, `validation_context`
  - `tools`, `toolsets`, `capabilities`
  - `defer_model_check`, `end_strategy`, `metadata`
  - `tool_timeout`, `max_concurrency`
- **When:** create the agent once at module level. mypy and pyright then catch a wrong `RunContext[...]` type or a wrong output type.
- **Example:**

  ```python
  from pydantic_ai import Agent, RunContext

  roulette = Agent('test', deps_type=int, output_type=bool, instructions='Use roulette_wheel to check wins.')

  @roulette.tool
  async def roulette_wheel(ctx: RunContext[int], square: int) -> str:
      """check if the square is a winner"""
      return 'winner' if square == ctx.deps else 'loser'

  print(roulette.run_sync('Put my money on square eighteen', deps=18).output)   # bool
  ```
- **Gotchas:**
  - Unions and output functions may need explicit generics: `Agent[object, A | B](...)`.
  - The deps type now defaults to `object`, not `None`.
  - `defer_model_check=True` defers building the model, so tests need no API key.
- **Doc:** `docs/agent.md`

### Five ways to run
- **What it is:**
  - `run` / `run_sync` return an `AgentRunResult`.
  - `run_stream` / `run_stream_sync` are context managers that give a `StreamedRunResult`.
  - `run_stream_events` yields `AgentStreamEvent`s, ending with an `AgentRunResultEvent`.
  - `iter` gives an `AgentRun` you step through node by node.
- **When:**
  - `run_sync`: scripts.
  - `run`: servers.
  - `run_stream`: streaming text to a UI.
  - `run_stream_events`: every event, including tool calls.
  - `iter`: full control.
- **Example:**

  ```python
  from pydantic_ai import Agent, AgentRunResultEvent

  agent = Agent('openai:gpt-6.1-sol')
  print(agent.run_sync('Capital of Italy?').output)

  async def main():
      async with agent.run_stream('Capital of the UK?') as response:
          async for text in response.stream_text():             # growing snapshot
              print(text)
      async with agent.run_stream_events('Capital of Mexico?') as events:
          async for ev in events:
              if isinstance(ev, AgentRunResultEvent):
                  print(ev.result.output)
  ```
- **Gotchas:**
  - `run_stream` treats the **first** output that matches the output type as final. Tool calls the model makes after that streamed text are **not executed**. Use `run_stream_events`, `iter` or `run(event_stream_handler=...)` if tools must run.
  - You can't call `run_sync` inside a sync tool. Make the delegating tool `async`.
  - Every run method also accepts these per-run overrides: `output_type`, `model`, `instructions`, `capabilities`, `retries`, `timeout`, `cancellation_token`, `conversation` and `metadata`.
- **Doc:** `docs/agent.md#running-agents`

### Event streams and custom events
- **What it is:**
  - `event_stream_handler=` and `run_stream_events` expose `PartStartEvent`, `PartDeltaEvent`, `FunctionToolCallEvent`, `FunctionToolResultEvent` and `FinalResultEvent`.
  - You can define your own `CustomEvent` dataclasses, emit them with `await ctx.emit(...)`, and listen with `@agent.on_event(...)`.
- **When:** progress updates from tools, or data for AG-UI and Vercel AI frontends that shouldn't go into the model's context.
- **Example:**

  ```python
  from dataclasses import dataclass
  from pydantic_ai import Agent, CustomEvent, RunContext

  @dataclass(kw_only=True)
  class SyncProgressEvent(CustomEvent):     # wire name: 'sync_progress'
      done: int
      total: int

  agent = Agent('test')

  @agent.on_event(SyncProgressEvent)
  async def record(ctx: RunContext, event: SyncProgressEvent) -> None:
      print(event.done, event.total, event.tool_name)      # tool_name/tool_call_id stamped automatically

  @agent.tool
  async def sync_files(ctx: RunContext, count: int) -> str:
      for i in range(1, count + 1):
          await ctx.emit(SyncProgressEvent(done=i, total=count))
      return f'Synchronized {count} files.'
  ```
- **Gotchas:**
  - Only async tools can emit events.
  - Event names are registered for the whole process.
  - These field names are reserved: `data`, `tool_call_id`, `tool_name` and `event_kind`.
  - Capabilities must emit `CapabilityEvent` instead.
  - Set `ui=False` on events that should stay server-side.
- **Doc:** `docs/agent.md#custom-events`

### Iterating the graph (`iter`)
- **What it is:** `async with agent.iter(...) as run:` lets you iterate over the nodes.
  - Drive it manually with `await run.next(node)`.
  - Check node types with `Agent.is_model_request_node`, `is_call_tools_node` and `is_end_node`.
  - Stream inside a node with `node.stream(run.ctx)`.
- **When:** to run your own logic between steps, stream both events and validated output, or edit a node before it runs.
- **Example:**

  ```python
  async def main():
      async with agent.iter('What is the capital of France?') as run:
          async for node in run:
              if Agent.is_model_request_node(node):
                  print('request:', node.request.parts)
              elif Agent.is_call_tools_node(node):
                  print('response:', node.model_response.parts)
      print(run.result.output, run.usage)          # cost is a best-effort genai-prices estimate
  ```
- **Gotchas:**
  - Don't pass an `End` node to `next()`.
  - A bare `async for` loop doesn't surface emitted events.
- **Doc:** `docs/agent.md#iterating-over-an-agents-graph`

### Cancellation
- **What it is:** create a `CancellationToken`, pass it to a run, then call `token.cancel()`. The run raises `RunCancelled`, which carries resumable messages. Other ways to cancel:
  - `ctx.cancel()` from inside the run;
  - `AgentRunEvents.cancel()`, `AgentRun.cancel()` or `StreamedRunResult.cancel()`.
  
  If the task is cancelled externally, you get the usual `CancelledError`. Recover the messages with `RunCancelled.from_cancellation(exc)`.
- **When:** stop buttons, and cancelling from another thread (the only way to stop a blocked `run_sync`). One shared token can cancel a parent and its sub-agents together.
- **Example:**

  ```python
  import asyncio
  from pydantic_ai import Agent, CancellationToken, RunCancelled

  agent = Agent('test')
  started = asyncio.Event()

  @agent.tool_plain
  async def slow_lookup() -> str:
      started.set(); await asyncio.sleep(10); return 'result'

  async def main():
      token = CancellationToken()        # single-use: one per run
      task = asyncio.create_task(agent.run('Look it up', cancellation_token=token))
      await started.wait(); token.cancel()
      try:
          await task
      except RunCancelled as exc:
          await agent.run(message_history=exc.all_messages())     # dangling tool call auto-repaired
  ```
- **Gotchas:**
  - Cancellation is cooperative. A `def` (non-async) tool keeps running, and its side effects remain.
  - Partial messages get `state='interrupted'`, and their usage is only partially counted.
- **Doc:** `docs/agent.md#cancelling-a-run`

### Instructions vs. system prompts
- **What it is:**
  - **Instructions** come in three forms: static (`Agent(instructions=)`), dynamic (`@agent.instructions`, re-evaluated before **every** request) and runtime (`run(instructions=)`). Only the current agent's instructions are sent.
  - **`system_prompt`** is stored in the message history and reused on later runs.
- **When:**
  - Prefer instructions.
  - Use `on_change='append'` for state that changes during a conversation. The change is appended as an `InstructionDeltaPart` instead of rewriting the start of the prompt, which keeps the prompt cache valid.
  - Use `system_prompt` only when later agents must keep receiving it.
- **Example:**

  ```python
  from datetime import date
  from pydantic_ai import Agent, RunContext

  agent = Agent('test', deps_type=str, instructions="Use the customer's name.")   # static

  @agent.instructions                                     # dynamic
  def user_name(ctx: RunContext[str]) -> str:
      return f"The user's name is {ctx.deps}."

  @agent.instructions(name='date', on_change='append')    # changes appended, cache kept
  def today() -> str:
      return f'The date is {date.today()}.'

  agent.run_sync('What is the date?', deps='Frank', instructions='Reply in French.')   # runtime
  ```
- **Gotchas:**
  - Returning `''` or `None` adds nothing, or withdraws an earlier instruction.
  - **Never build instructions from untrusted text.**
  - A dynamic `system_prompt` runs once per conversation unless you set `dynamic=True` or `on_change='append'`.
- **Doc:** `docs/agent.md#instructions`

### Dependencies
- **What it is:** declare `deps_type=` on the agent (usually a dataclass), pass `deps=` on each run, and read `ctx.deps` in instructions, tools, validators and hooks. Swap the deps in tests with `agent.override(deps=...)`.
- **When:** to give the agent DB connections, HTTP clients, API keys or a tenant ID without using globals.
- **Example:**

  ```python
  from dataclasses import dataclass
  import httpx
  from pydantic_ai import Agent, RunContext

  @dataclass
  class MyDeps:
      api_key: str
      http_client: httpx.AsyncClient

  agent = Agent('openai:gpt-6.1-sol', deps_type=MyDeps)

  @agent.tool
  async def joke_material(ctx: RunContext[MyDeps], subject: str) -> str:
      r = await ctx.deps.http_client.get('https://example.com', params={'subject': subject},
                                         headers={'Authorization': f'Bearer {ctx.deps.api_key}'})
      return r.text
  ```
- **Gotchas:**
  - `deps_type` is only used for type checking.
  - Sync functions run in a thread pool, so prefer `async` for I/O.
  - `TemplateStr('Hi {{name}}')` renders fields from your deps.
- **Doc:** `docs/dependencies.md`

### Structured output
- **What it is:** `output_type` accepts:
  - scalars, `TypedDict`s, dataclasses and `BaseModel`s;
  - unions or lists of types, where each member becomes its own output tool;
  - `StructuredDict(schema)`;
  - `Choices({...})` (new), for options known only at run time. `Choice(desc, value=...)` maps a key to an object or to a callable action.
- **When:** extracting data, returning either data or a question back to the user (`[Model, str]`), and classification.
- **Example:**

  ```python
  from pydantic import BaseModel
  from pydantic_ai import Agent, Choices

  class Box(BaseModel):
      width: int
      height: int
      depth: int
      units: str

  extractor = Agent('openai:gpt-6-luna', output_type=[Box, str], instructions='Extract box dims or ask.')
  print(extractor.run_sync('The box is 10x20x30 cm').output)     # width=10 height=20 depth=30 units='cm'
  triage = Agent('openai:gpt-6.1-sol', output_type=Choices({'refund': 'Wants money back.', 'replace': 'Wants a new unit.'}))
  ```
- **Gotchas:**
  - **`StructuredDict` output is not validated.**
  - With `str | None`, the run returns `None` when the model finishes without saying anything.
  - Text cut off by the token limit is still returned. Check `result.response.finish_reason == 'length'`.
  - Structured output cut off by the token limit raises `OutputTokenLimitExceeded`.
  - `output_type=BinaryImage` returns a generated image.
- **Doc:** `docs/output.md#structured-output`, `#choices`, `#optional-output`, `#image-output`

### Output functions and `TextOutput`
- **What it is:** a function passed as `output_type`. The model must call it, the call ends the run, and the function's return value becomes the output. It can take `ctx` and raise `ModelRetry`. `TextOutput(fn)` lets the model answer in plain text, which is then passed to `fn(text: str)`.
- **When:** post-processing with retries, or a router agent that hands off to sub-agents.
- **Example:**

  ```python
  from pydantic_ai import Agent, ModelRetry, RunContext, TextOutput

  def run_sql_query(ctx: RunContext, query: str) -> list[str]:
      """Run a SQL query on the database."""
      if not query.upper().startswith('SELECT'):
          raise ModelRetry('Only SELECT queries are supported.')
      return ['Amsterdam', 'Mexico City']

  def split_into_words(text: str) -> list[str]:
      return text.split()

  sql_agent = Agent('openai:gpt-6.1-sol', output_type=run_sql_query)
  words_agent = Agent('openai:gpt-6.1-sol', output_type=TextOutput(split_into_words))
  ```
- **Gotchas:**
  - When streaming, output functions and validators run on **every partial output**. Guard side effects with `ctx.partial_output`.
  - `stream_text()` skips `TextOutput`.
- **Doc:** `docs/output.md#output-functions`

### Output modes and `end_strategy`
- **What it is:** three ways to get structured output:
  - `ToolOutput` (default): an output tool. Options: `name`, `description`, `max_retries`, `strict`, `sequential`.
  - `NativeOutput`: the provider's JSON-schema mode.
  - `PromptedOutput`: the schema goes in the instructions; `template=` customizes it.

  `end_strategy` controls tool calls that arrive alongside the final output: `'graceful'` (default, runs them), `'early'` (skips them) or `'exhaustive'` (runs all).
- **When:** use `NativeOutput` where a model supports it, or where streamed tool arguments are poor. Use `PromptedOutput` for weak or local models.
- **Example:**

  ```python
  from pydantic import BaseModel
  from pydantic_ai import Agent, NativeOutput, PromptedOutput, ToolOutput

  class Fruit(BaseModel):
      name: str
      color: str

  class Vehicle(BaseModel):
      name: str
      wheels: int

  tool_mode = Agent('openai:gpt-6.1-sol', output_type=[ToolOutput(Fruit, name='return_fruit', max_retries=2), Vehicle])
  native_mode = Agent('openai:gpt-6.1-sol', output_type=NativeOutput([Fruit, Vehicle]))
  prompted_mode = Agent('openai:gpt-6.1-sol', output_type=PromptedOutput([Fruit, Vehicle], template='JSON: {schema}'))
  ```
- **Gotchas:**
  - `NativeOutput` has per-provider limits.
  - Streaming always behaves like `'early'`.
  - **The docs are ambiguous here:** they mention an "agent-wide `prepare_output_tools`", but `Agent()` has no such kwarg. In source, it is the `PrepareOutputTools` capability or `Hooks(prepare_output_tools=...)`.
- **Doc:** `docs/output.md#output-modes`

### Output validators and validation context
- **What it is:** `@agent.output_validator` functions return the output (possibly changed) or raise `ModelRetry`. `Agent(validation_context=...)` takes a value or `ctx → value`, which Pydantic validators receive as `info.context`.
- **When:** validation that needs I/O, such as running `EXPLAIN` on generated SQL.
- **Example:**

  ```python
  @agent.output_validator
  async def validate_sql(ctx: RunContext[DatabaseConn], output: Success) -> Success:    # your own types
      if ctx.partial_output:
          return output
      try:
          await ctx.deps.execute(f'EXPLAIN {output.sql_query}')
      except QueryError as e:
          raise ModelRetry(f'Invalid query: {e}') from e
      return output
  ```
- **Gotchas:**
  - Each retry uses the **output** budget, which defaults to 1.
  - The validation context is never sent to the model.
- **Doc:** `docs/output.md#output-validator-functions`

### Streaming text and structured output
- **What it is:** the `StreamedRunResult` methods:
  - `stream_text(delta=False, debounce_by=0.1)`;
  - `stream_output()`, which yields partially validated snapshots;
  - `stream_response()`;
  - `get_output()`;
  - `cancel()`;
  - `.result`, which gives the settled `AgentRunResult`.
- **When:** live chat UIs and progressively rendered forms.
- **Example:**

  ```python
  from typing import NotRequired
  from typing_extensions import TypedDict
  from pydantic_ai import Agent

  class UserProfile(TypedDict):
      name: str
      bio: NotRequired[str]

  agent = Agent('openai:gpt-6.1-sol', output_type=UserProfile)

  async def main():
      async with agent.run_stream('My name is Ben, I like dogs.') as result:
          async for profile in result.stream_output(debounce_by=None):
              print(profile)                   # accumulated snapshot, not a delta
          stored = result.result
  ```
- **Gotchas:**
  - `stream_text(delta=True)` doesn't add the final message to history.
  - Structured streaming needs a provider that streams tool arguments.
- **Doc:** `docs/output.md#streamed-results`

### Usage limits and cost
- **What it is:** `UsageLimits` caps a run:
  - `request_limit` (default **50**);
  - `tool_calls_limit`;
  - input/output/total/per-request token limits;
  - `cost_limit` (a `Decimal`, in USD).

  Exceeding a limit raises `UsageLimitExceeded`. Cost estimates come from genai-prices. Call `prices.update_in_background()` to keep prices current.
- **When:** stopping runaway loops and capping spend. Tools can read `ctx.usage_limits` to adapt.
- **Example:**

  ```python
  from decimal import Decimal
  from pydantic_ai import Agent, UsageLimitExceeded, UsageLimits

  agent = Agent('anthropic:claude-sonnet-5-5')
  try:
      r = agent.run_sync('Capital of Italy?', usage_limits=UsageLimits(request_limit=25, cost_limit=Decimal('0.50')))
      print(r.usage)        # RunUsage(cost=Decimal(...), input_tokens=..., output_tokens=..., requests=1)
  except UsageLimitExceeded as e:
      print(e)
  ```
- **Gotchas:**
  - Token and cost limits are checked **after** billing.
  - `cost` is `None` for models genai-prices doesn't have prices for.
  - Limits reset each run unless you pass `conversation=`.
  - A sub-agent that shares `usage=ctx.usage` also needs `usage_limits=ctx.usage_limits`.
- **Doc:** `docs/agent.md#usage-limits`

### Model settings, metadata and concurrency
- **What it is:**
  - `ModelSettings` is a TypedDict (`temperature`, `max_tokens`, `timeout`, `max_retries`, `tool_choice`, `thinking`, `cache`, `extra_body`, and more).
  - Settings merge in order: model → agent → capability → run.
  - Agent-level and run-level settings can also be `lambda ctx: ...`, evaluated before each request.
  - `metadata=` tags the result and its trace span.
  - `max_concurrency=` (or `ConcurrencyLimit(max_running, max_queued)`) caps how many runs execute at once.
- **When:** deterministic first steps; provider-specific settings classes (e.g. `GoogleModelSettings`); tagging traces by tenant; backpressure.
- **Example:**

  ```python
  from pydantic_ai import Agent, ConcurrencyLimit, ModelSettings
  from pydantic_ai.models.google import GoogleModel

  model = GoogleModel('gemini-3.8-flash', settings=ModelSettings(temperature=0.8, max_tokens=500))
  agent = Agent(model, model_settings=ModelSettings(temperature=0.5), metadata={'tenant': 't-1'},
                max_concurrency=ConcurrencyLimit(max_running=10, max_queued=100))
  agent.run_sync('Capital of Italy?', model_settings=ModelSettings(temperature=0.0))   # temp 0.0, max_tokens 500
  stepwise = Agent('test', model_settings=lambda ctx: ModelSettings(temperature=0.0 if ctx.run_step <= 1 else 0.7))
  ```
- **Gotchas:**
  - Unsupported tuning settings are ignored silently. Only settings that change guarantees (`timeout`, `max_retries`, `extra_*`) warn, with `UnsupportedSettingWarning`.
  - `thinking` is dropped silently if the model's profile lacks support.
- **Doc:** `docs/agent.md#model-run-settings`

### Multimodal and structured input
- **What it is:** a prompt can be a list mixing:
  - `str`;
  - `ImageUrl`, `AudioUrl`, `VideoUrl`, `DocumentUrl`;
  - `BinaryContent`;
  - `TextContent`;
  - `StructuredContent(value, tag=)` (new, and stays typed in history);
  - `UploadedFile(file_id, provider_name=model.system)`.
- **When:** vision, PDFs, sending app state as data, or using files from a provider's file store.
- **Example:**

  ```python
  from pathlib import Path
  from pydantic import BaseModel
  from pydantic_ai import Agent, BinaryContent, ImageUrl, StructuredContent

  class UIState(BaseModel):
      url: str
      cart_total: float

  agent = Agent('anthropic:claude-sonnet-5-5')
  agent.run_sync(['What company is this logo from?', ImageUrl(url='https://iili.io/3Hs4FMg.png')])
  agent.run_sync(['Summarize.', BinaryContent(data=Path('doc.pdf').read_bytes(), media_type='application/pdf')])
  agent.run_sync([StructuredContent(UIState(url='/p/42', cart_total=949.0), tag='ui_state'), 'Why did it jump?'])
  ```
- **Gotchas:**
  - URL support varies by provider (see the table in the doc).
  - `force_download=True` downloads files locally, with SSRF protection and a 50 MiB cap.
  - **Never build file URLs from untrusted input:** `s3://` and `gs://` URLs are fetched with your own IAM credentials.
- **Doc:** `docs/input.md`

### Message history and conversations
- **What it is:**
  - `result.all_messages()` and `new_messages()`, plus `*_json()` variants.
  - `message_history=` passes the messages only.
  - `conversation=result.conversation` carries messages, usage, conversation ID and pending deferred calls together.
  - Every message records a `run_id` and a `conversation_id`.
- **When:** multi-turn chat, switching models mid-conversation (the message format is model-agnostic), handing off between agents, and forking (`conversation_id='new'`).
- **Example:**

  ```python
  from pydantic_ai import Agent

  agent = Agent('openai:gpt-6.1-sol', instructions='Be a helpful assistant.')
  r1 = agent.run_sync('Tell me a joke.')
  r2 = agent.run_sync('Explain?', conversation=r1.conversation)                      # preferred in V2
  r3 = agent.run_sync('Explain?', message_history=r1.new_messages(), model='anthropic:claude-sonnet-5-5')
  fork = agent.run_sync('Another joke.', message_history=r1.all_messages(), conversation_id='new')
  assert r1.conversation_id == r2.conversation_id and r2.usage.requests == 2
  ```
- **Gotchas:**
  - When history is given, **no new system prompt** is added (use `ReinjectSystemPrompt` if you need it).
  - `conversation=` can't be combined with `message_history=`.
  - Don't mutate messages in place; build new ones with `dataclasses.replace`.
- **Doc:** `docs/message-history.md`

### Serialization and untrusted history
- **What it is:**
  - `ModelMessagesTypeAdapter` and `ConversationTypeAdapter` round-trip history with full fidelity.
  - An `AgentRunResult` can be a field on a Pydantic model.
  - `sanitize_messages()` cleans history that came from a client.
  - `repair_messages()` closes out tool calls left without results.
- **Example:**

  ```python
  from pydantic_ai import Agent, ConversationTypeAdapter, ModelMessagesTypeAdapter
  from pydantic_ai.messages import repair_messages, sanitize_messages

  agent = Agent('openai:gpt-6.1-sol')
  result = agent.run_sync('Tell me a joke.')
  history = ModelMessagesTypeAdapter.validate_json(result.all_messages_json())
  stored = ConversationTypeAdapter.dump_json(result.conversation)       # key it by result.conversation_id
  agent.run_sync('Explain?', conversation=ConversationTypeAdapter.validate_json(stored))
  safe = repair_messages(sanitize_messages(ModelMessagesTypeAdapter.validate_python(client_json)))
  ```
- **Gotchas:**
  - **Clients can forge tool calls and approvals in the history they send.** Your endpoint is the authorization boundary.
  - Never resume history from a client that ends in `state='suspended'`.
- **Doc:** `docs/message-history.md#storing-and-loading-messages-to-json`

### History processors (`ProcessHistory`)
- **What it is:** the `ProcessHistory(fn)` capability rewrites the message list before **every** request.
  - `fn(messages)` or `fn(ctx, messages)`, sync or async.
  - Multiple processors chain in order.
  - `ctx.context_window_used` gives the fraction of the context window in use.
- **When:** trimming history, redacting PII, summarizing into a `CompactionPart`, or compacting once the context window is about 80% full.
- **Example:**

  ```python
  from pydantic_ai import Agent, ModelMessage, RunContext
  from pydantic_ai.capabilities import ProcessHistory

  def keep_recent(messages: list[ModelMessage]) -> list[ModelMessage]:
      return messages[-5:]

  def compact_when_full(ctx: RunContext, messages: list[ModelMessage]) -> list[ModelMessage]:
      used = ctx.context_window_used              # None when unknown
      return messages if used is None or used <= 0.8 else messages[-4:]

  agent = Agent('openai:gpt-6.1-sol', capabilities=[ProcessHistory(keep_recent), ProcessHistory(compact_when_full)])
  ```
- **Gotchas:**
  - The V1 `history_processors=` kwarg was **removed**.
  - Processors *replace* the stored history.
  - If you separate a tool call from its result, it gets silently repaired, which changes what the model sees.
- **Doc:** `docs/message-history.md#processing-message-history`

### Injecting messages mid-run
- **What it is:** add messages while a run is going.
  - Use `ctx.enqueue(...)` from tools and hooks, or `run.enqueue(...)` when driving `iter()`.
  - `priority='asap'` (default) delivers on the next request.
  - `'when_idle'` delivers only when the agent would otherwise stop.
  - `dequeue(id)` and `set_enqueue_priority(id, ...)` change a queued message.
- **When:** a user types while the agent is working, webhooks, background results.
- **Example:**

  ```python
  from pydantic_ai import Agent, RunContext
  from pydantic_graph import End

  agent = Agent('anthropic:claude-opus-5-5')

  @agent.tool
  def trigger_alert(ctx: RunContext) -> str:
      ctx.enqueue('Alert: production is degraded, prioritize triage.')
      return 'alert raised'

  async def main():
      async with agent.iter('Summarize the deploy report') as run:
          run.enqueue('Also include the new error.', priority='when_idle')
          node = run.next_node
          while not isinstance(node, End):
              node = await run.next(node)
  ```
- **Gotchas:**
  - Never enqueue untrusted data as a `SystemPromptPart`.
  - Enqueuing on every step loops forever, so keep `UsageLimits` on.
- **Doc:** `docs/message-history.md#injecting-messages-mid-run`

### Retries
- **What it is:** there are nine retry layers, and **they don't share budgets**: transport, provider SDK, durable engine, `RetryOnModelErrors`, fallback, `RetryModelRequest`, tool, output, and model-request hooks. You configure the agent-level budgets like this:
  - `retries=N`, or `retries={'tools': N, 'output': M}`, on the agent, the run or `override`;
  - per tool: `@agent.tool(retries=N)`;
  - per output tool: `ToolOutput(max_retries=N)`.
- **When:**
  - Raise `ModelRetry` to ask the model to fix its call. It shows up in history as `outcome='retried'`.
  - Raise `ToolFailed` for a definitive failure. It shows up as `outcome='failed'` and uses **no** budget.
  - Add `RetryOnModelErrors` to retry 429s and 5xx errors.
- **Example:**

  ```python
  from pydantic_ai import Agent, ModelRetry, RunContext, ToolFailed
  from pydantic_ai.capabilities import RetryOnModelErrors

  agent = Agent('openai:gpt-6.1-sol', retries={'tools': 3, 'output': 2}, capabilities=[RetryOnModelErrors(max_attempts=4)])

  @agent.tool(retries=2)
  def get_user_by_name(ctx: RunContext, name: str) -> int:
      """Get a user's ID from their full name."""
      if ' ' not in name:
          raise ModelRetry('Provide the full name.')
      if name == 'Ghost User':
          raise ToolFailed('No such user exists.')
      return 123
  ```
- **Gotchas:**
  - Layers **multiply** (N×F×M×K), so pick one layer to own retries.
  - A tool's retry count resets after it succeeds.
  - Any other exception aborts the run unless an `on_tool_execute_error` hook converts it.
  - `RetryPromptPart` is deprecated; use `is_retry()`.
- **Doc:** `docs/retries.md`

### Model errors and recovering failed runs
- **What it is:**
  - `capture_run_messages()` keeps the history of a run that raises (`UnexpectedModelBehavior`, `UsageLimitExceeded`, and so on). Its partial parts have `state='interrupted'`.
  - To resume, pass that history as `message_history` with **no new prompt**. Tools that already finished don't run again.
  - `AgentRunError.conversation` and `capture_run_conversation()` give you a storable `Conversation`.
- **Example:**

  ```python
  from pydantic_ai import Agent, UnexpectedModelBehavior, UsageLimitExceeded, UsageLimits, capture_run_messages

  agent = Agent('openai:gpt-6.1-sol')

  def answer(prompt: str) -> str:
      with capture_run_messages() as messages:
          try:
              return agent.run_sync(prompt, usage_limits=UsageLimits(request_limit=3)).output
          except (UsageLimitExceeded, UnexpectedModelBehavior) as e:
              print('failed:', e, repr(e.__cause__))
      return agent.run_sync(message_history=messages).output      # resume outside the block
  ```
- **Gotchas:**
  - A capture block records only its **first** run.
  - A resumed run's usage restarts at zero; pass `conversation=` to keep counting.
- **Doc:** `docs/agent.md#model-errors`, `#recovering-a-failed-run`

### Timeouts
- **What it is:**
  - `ModelSettings` timeouts:
    - `timeout`: one attempt, enforced by the provider SDK.
    - `request_timeout`: one clock across all attempts, enforced by Pydantic AI for every model.
    - `first_event_timeout`: the wait for a stream to start; when it expires, a fallback model takes over.
  - `tool_timeout=` / per-tool `timeout=`: a timeout comes back to the model as a retry.
  - `timeout=` on a hook bounds that hook.
  - `run(..., timeout=s)` raises `RunTimedOut`, which is both a `RunCancelled` and a `TimeoutError`.
  - `ctx.remaining_time()` tells a tool how long the run has left.
- **When:** SLAs, failing over fast, and sizing work to the time left.
- **Example:**

  ```python
  from pydantic_ai import Agent, ModelRequestTimeout, RunContext, RunTimedOut

  agent = Agent('openai:gpt-6.1-sol', tool_timeout=30, model_settings={'timeout': 30, 'request_timeout': 90})

  @agent.tool
  async def research(ctx: RunContext, topic: str) -> str:
      left = ctx.remaining_time()
      return 'Not enough time.' if left is not None and left < 10 else f'Notes on {topic}'

  async def main():
      try:
          print((await agent.run('Research batteries', timeout=60)).output)
      except RunTimedOut as exc:
          resume_from = exc.all_messages()
      except ModelRequestTimeout as e:
          print(e.model_name, e.timeout)
  ```
- **Gotchas:**
  - `tool_timeout` doesn't apply to `FunctionToolset`s you build yourself.
  - Timing out a sync `def` tool doesn't actually stop it.
  - Sub-agents inherit the parent's deadline.
- **Doc:** `docs/timeouts.md`

### Direct model requests
- **What it is:** `pydantic_ai.direct.model_request` and its `_sync`, `_stream`, `_stream_sync` and `_batch` variants. One provider-agnostic call, with no agent loop, no tool execution and no output validation.
- **When:** building your own abstractions. For tools, pass `ModelRequestParameters(function_tools=[...])`.
- **Example:**

  ```python
  from pydantic_ai import ModelRequest
  from pydantic_ai.direct import model_request_sync

  resp = model_request_sync('anthropic:claude-haiku-5-5',
                            [ModelRequest.user_text_prompt('What is the capital of France?')], instrument=True)
  print(resp.text, resp.usage)        # RequestUsage(input_tokens=56, output_tokens=7)
  ```
- **Gotchas:**
  - Only the most recent `instructions` apply.
  - No capabilities apply here; for retries, use a retrying transport.
- **Doc:** `docs/direct.md`

### Citations
- **What it is:** `TextPart.citations` holds `Citation(sources=[...], anchor=...)` objects in the same shape for every provider. The `Citations()` capability asks for citations from providers where they are opt-in.
- **When:** grounded answers from web search, web fetch or documents you send.
- **Example:**

  ```python
  from pydantic_ai import Agent, BinaryContent, TextPart
  from pydantic_ai.capabilities import Citations

  agent = Agent('anthropic:claude-sonnet-5-5', capabilities=[Citations()])
  result = agent.run_sync(['Return window?', BinaryContent(data=b'Items may be returned within 30 days.',
                                                           media_type='text/plain')])
  for part in result.response.parts:
      if isinstance(part, TextPart):
          for c in part.citations or []:
              print(c.anchor, [s.excerpts for s in c.sources])
  ```
- **Gotchas:**
  - Citations attach to **text output only**. Structured output gets none, and Anthropic's citation markup can leak into tool arguments.
  - When streaming, citations may arrive late, so read them from the final response.
- **Doc:** `docs/citations.md`

### Image generation (`ImageGenerator`)
- **What it is:** one API for OpenAI GPT Image, Gemini and xAI Grok Imagine.
  - `generate()` and `generate_sync()`.
  - Edit existing images with `images=[...]`.
  - `ImageGenerationSettings(dimensions=...)` or `aspect_ratio=`.
- **When:** your *application* decides when to make an image. When the *agent* should decide, use the `ImageGeneration` capability or `output_type=BinaryImage`.
- **Example:**

  ```python
  from pathlib import Path
  from pydantic_ai import ImageGenerator
  from pydantic_ai.images import ImageGenerationSettings

  gen = ImageGenerator('openai:gpt-image-2.5-flare')
  result = gen.generate_sync('Minimalist coffee-shop logo.', settings=ImageGenerationSettings(aspect_ratio='16:9'))
  Path('logo.png').write_bytes(result.image.data)
  edited = gen.generate_sync('Make the cup blue.', images=[result.image])
  ```
- **Gotchas:**
  - DALL·E models are rejected.
  - A shape the model can't produce raises `UserError` before the request is sent.
  - A moderation block raises `ContentFilterError`.
  - Test with `TestImageGenerationModel`.
- **Doc:** `docs/image-generation.md`

### Embeddings (`Embedder`)
- **What it is:** one API for OpenAI (and compatible), Google, Cohere, VoyageAI, Bedrock and local `sentence-transformers:` models.
  - `embed_query()` and `embed_documents()`, plus `_sync` versions.
  - Results can be indexed by position or by input text.
  - Usage and `cost()` are reported.
  - `EmbeddingSettings(dimensions=, truncate=)`.
  - `count_tokens()`.
- **When:** semantic search, DIY RAG, deduplication.
- **Example:**

  ```python
  from pydantic_ai import Embedder
  from pydantic_ai.embeddings import EmbeddingSettings

  embedder = Embedder('openai:text-embedding-3-small', settings=EmbeddingSettings(dimensions=512))
  q = embedder.embed_query_sync('What is machine learning?')
  docs = embedder.embed_documents_sync(['ML is a subset of AI.', 'Python is a language.'])
  print(len(q[0]), len(docs.embeddings), docs.usage.input_tokens)
  local = Embedder('sentence-transformers:google/embeddinggemma-300m')      # no API key
  ```
- **Gotchas:**
  - Use `embed_query` for queries and `embed_documents` for content.
  - Switching models means re-embedding everything.
  - There is no vector DB or reranker built in.
  - Test with `TestEmbeddingModel`.
- **Doc:** `docs/embeddings.md`

### Batch processing
- **What it is:** provider batch APIs (Anthropic, OpenAI Responses, Gemini) at about 50% of the normal price, returning within about 24 hours.
  - The `BatchModelRequests` capability groups requests from concurrent runs into batches.
  - With `PendingModelResponse` in the `output_type`, a run ends as soon as it is submitted. You resume it later from its stored history.
  - `model_request_batch()` is the lower-level API.
- **Example:**

  ```python
  import asyncio
  from pydantic import BaseModel
  from pydantic_ai import Agent, PendingModelResponse
  from pydantic_ai.capabilities import BatchModelRequests

  class Triage(BaseModel):
      category: str
      urgent: bool

  agent = Agent('anthropic:claude-sonnet-5-5', output_type=[Triage, PendingModelResponse],
                capabilities=[BatchModelRequests()])

  async def submit(tickets: list[str]) -> list[bytes]:
      results = await asyncio.gather(*(agent.run(t) for t in tickets))       # started together -> one batch
      return [r.all_messages_json() for r in results]     # later: agent.run(message_history=...) collects
  ```
- **Gotchas:**
  - Every tool round trip is another batch round trip.
  - Runs started one after another each wait `max_wait` (30 s).
  - Resume with the capability still configured.
  - `TestModel` and `FunctionModel` process batches in memory.
- **Doc:** `docs/batch.md`

### Persistence (`Conversation`, `ConversationStore`)
- **What it is:** store sessions as `Conversation` objects. A `ConversationStore` provides:
  - append-only saves;
  - conflict detection (`ConversationConflict`);
  - `scope=` per owner;
  - `branch` and `fork`.

  `InMemoryConversationStore` is for tests. The Harness adds `StepPersistence` and `Memory`.
- **When:** chat threads and support tickets. A `jsonb` column is enough; you don't need durable execution for this.
- **Example:**

  ```python
  from pydantic_ai import Agent, Conversation
  from pydantic_ai.conversation_store import ConversationStore

  agent = Agent('openai:gpt-6.1-sol', instructions='Be a helpful assistant.')

  async def chat(store: ConversationStore, conversation_id: str, prompt: str) -> str:
      conversation = await store.load(conversation_id) or Conversation(conversation_id=conversation_id)
      result = await agent.run(prompt, conversation=conversation)
      await store.save(result)            # appends only the new messages
      return result.output
  ```
- **Gotchas:**
  - A conversation ID is a key, not a credential, so check access.
  - Store Pydantic AI's message shape, not the UI protocol's shape.
- **Doc:** `docs/persistence.md`

### Agent specs (YAML/JSON)
- **What it is:** an `AgentSpec` holds `model`, `instructions`, `model_settings`, `capabilities`, `retries`, `deps_schema`, `output_schema` and more.
  - Load one with `Agent.from_file()` or `Agent.from_spec(dict, **overrides)`.
  - `AgentSpec.to_file()` also writes a JSON Schema for editor autocomplete.
  - `{{var}}` becomes a `TemplateStr`, filled from your deps.
- **When:** keep configuration out of code, or let non-developers tune prompts.
- **Example:**

  ```yaml
  # agent.yaml (requires the `spec` extra)
  model: anthropic:claude-opus-5-5
  instructions: "You are assisting {{name}}, who is a {{role}}."
  retries: {tools: 3, output: 2}
  capabilities:
    - WebSearch: {local: duckduckgo}
    - Thinking: {effort: high}
  ```

  ```python
  agent = Agent.from_file('agent.yaml', deps_type=UserProfile)       # template vars checked against deps
  ```
- **Gotchas:**
  - A spec can only use serializable capabilities. Custom ones need `custom_capability_types=`.
  - **`output_schema` is not validated.**
  - A spec has the authority of code; for example, it can point the agent at any MCP URL.
- **Doc:** `docs/agent-spec.md`

### Hooks (`Hooks` capability)
- **What it is:** interception at every stage, in the order `wrap_* → before_* → operation (on_*_error) → after_*`. Stages:
  - run;
  - node;
  - model request (before / prepare / after / wrap / error);
  - tool validation and execution;
  - output validation and processing;
  - `prepare_tools`, deferred tool calls and events.

  Register a hook with `@hooks.on.<name>` or a constructor kwarg. Filter tool hooks with `tools=[...]`, and bound a hook with `timeout=`.
- **When:** logging, request rewriting, tool audits, turning exceptions into `ModelRetry`/`ToolFailed`, auto-approving tools.
- **Example:**

  ```python
  from pydantic_ai import Agent, ModelRequestContext, RunContext
  from pydantic_ai.capabilities import Hooks

  hooks = Hooks()

  @hooks.on.before_model_request
  async def log_request(ctx: RunContext, request_context: ModelRequestContext) -> ModelRequestContext:
      print(f'step {ctx.run_step}: {len(request_context.messages)} messages')
      return request_context

  @hooks.on.before_tool_execute(tools=['send_email'], timeout=5)
  async def audit(ctx: RunContext, *, call, tool_def, args):
      print('audit:', call.tool_name, args)
      return args

  agent = Agent('test', capabilities=[hooks])
  ```
- **Gotchas:**
  - Error hooks: raise to propagate the error, return a value to recover.
  - `ModelRetry` from a model-request hook uses the **output** retry budget.
  - Changing `request_context.messages` affects this request only; `ctx.messages` is the persistent history.
  - Sync hooks run in threads.
- **Doc:** `docs/hooks.md`

### Extensibility
- **What it is:** capabilities are the main way to extend Pydantic AI. Package them as `pydantic-ai-*` with `get_serialization_name()` and `from_spec()`. Lower-level extension points:
  - `AbstractToolset` / `WrapperToolset`;
  - `Model` / `WrapperModel`;
  - `AbstractAgent` / `WrapperAgent`;
  - custom embedding and image models.
- **Example:**

  ```python
  agent = Agent.from_file('agent.yaml', custom_capability_types=[MyCapability])
  ```
- **Gotchas:** most new capabilities belong in the Harness, not in core.
- **Doc:** `docs/extensibility.md`

### Testing (`TestModel`, `FunctionModel`, `override`)
- **What it is:**
  - `TestModel` calls every tool with schema-valid arguments, then returns `'success (no tool calls)'`, a JSON summary, or schema-valid data. Options: `custom_output_text`, `custom_output_args`, `call_tools`.
  - `FunctionModel(fn)` scripts the model's responses.
  - `agent.override(model=, deps=)` swaps these in.
  - `models.ALLOW_MODEL_REQUESTS = False` blocks real requests.
- **When:** deterministic unit tests of your own code. Use evals to judge answer quality.
- **Example:**

  ```python
  from pydantic_ai import Agent, ModelMessage, ModelResponse, TextPart, models
  from pydantic_ai.models.function import AgentInfo, FunctionModel
  from pydantic_ai.models.test import TestModel

  models.ALLOW_MODEL_REQUESTS = False
  agent = Agent('openai:gpt-6.1-sol', defer_model_check=True)

  def scripted(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
      return ModelResponse(parts=[TextPart(f'{len(messages)} msgs, tools={[t.name for t in info.function_tools]}')])

  def test_agent():
      with agent.override(model=TestModel(custom_output_text='Sunny')):
          assert agent.run_sync('Weather?').output == 'Sunny'
      with agent.override(model=FunctionModel(scripted)):
          assert agent.run_sync('Hi').output == '1 msgs, tools=[]'
  ```
- **Gotchas:**
  - `TestModel` ignores regex `pattern` constraints and can't emulate native tools (use `override(native_tools=[])`).
  - To assert on messages, combine `capture_run_messages()` with `dirty_equals`.
- **Doc:** `docs/testing.md`

### Going to production
- **What it is:** a Q&A checklist plus a runnable FastAPI + DBOS + approval + Logfire service. The short answers:
  - crashes: durable execution;
  - approvals: `requires_approval=True` → `DeferredToolRequests` → resume with `deferred_tool_results`;
  - state: store the `Conversation`;
  - cost: `UsageLimits`, plus `SpendLimits` from the Harness;
  - outages: `ModelFallback` + `RetryOnModelErrors`;
  - tracing: `logfire.instrument_pydantic_ai()`;
  - frontend: `VercelAIAdapter.dispatch_request`;
  - deployment: your own Python process.
- **Example:**

  ```python
  from decimal import Decimal
  from pydantic_ai import Agent, UsageLimits
  from pydantic_ai.capabilities import Caching, ModelFallback, RetryOnModelErrors

  agent = Agent('anthropic:claude-sonnet-5-5', tool_timeout=30,
                capabilities=[RetryOnModelErrors(), ModelFallback('openai:gpt-6.1-sol'), Caching()])

  async def handle(prompt: str) -> str:
      limits = UsageLimits(request_limit=25, cost_limit=Decimal('0.50'))
      return (await agent.run(prompt, usage_limits=limits, timeout=120)).output
  ```
- **Gotchas:**
  - Approval guards against the *model*, not the client, so authorize inside tools.
  - Make tools idempotent, because durable replay re-runs steps that were in flight.
  - Traces include prompts unless you set `include_content=False`.
- **Doc:** `docs/production.md`

### Troubleshooting
- **What it is:** a debugging method:
  1. Reproduce the problem in one run.
  2. Trace it, and read what the model saw (`gen_ai.input.messages` / `gen_ai.tool.definitions`).
  3. Pin it down in a `FunctionModel` test.

  Plus fixes for common errors:
  - **Jupyter event loop:** use `await agent.run`.
  - **`request_limit of 50`:** raise the limit or pass `None`.
  - **Exceeded max retries:** improve docstrings or raise the budget.
  - **Unprocessed tool calls:** resume with no prompt, or use `repair_messages()`.
  - **Stale model profiles:** upgrade.
- **Example:**

  ```python
  import warnings
  from pydantic_ai.exceptions import UnsupportedSettingWarning
  warnings.filterwarnings('error', category=UnsupportedSettingWarning)     # surface ignored settings
  ```
- **Gotchas:**
  - **The docs are inconsistent here:** this page still mentions `RetryPromptPart`, which `retries.md` deprecates in favor of `ToolReturnPart(outcome='retried')` and `RetryFeedbackPart`. Use `is_retry()`.
- **Doc:** `docs/troubleshooting.md`

**Cross-links (covered by the other research files):**
- tools and toolsets: `docs/tools*.md`, `docs/toolsets.md`, `docs/deferred-tools.md`
- capabilities: `docs/capabilities/`
- models: `docs/models/`
- UI and realtime: `docs/ui/`, `docs/realtime/`
- durable execution: `docs/durable_execution/`
- graph and evals: `docs/graph.md`, `docs/evals.md`
- Logfire: `docs/logfire.md`
- Harness: `docs/harness/`

## 3. Experiment ideas (increasing difficulty)

1. **Offline hello-agent.** Build `Agent('test')` with one tool and a `BaseModel` output. Print `all_messages()` and `usage` to see what `TestModel` did.
2. **Run-mode tour.** Send one prompt through all five run methods and log every event and node. Then use a `FunctionModel` that returns text plus a tool call, and watch `run_stream` skip the tool.
3. **Deps and override tests.** Use dataclass deps wrapping a fake DB, with dynamic instructions and a tool. Write pytest tests with `agent.override(deps=..., model=FunctionModel(...))` and `ALLOW_MODEL_REQUESTS=False`.
4. **Output matrix.** Extract the same data with `ToolOutput`, `NativeOutput` and `PromptedOutput`. Add a `Choices` classifier and an `@output_validator` that raises `ModelRetry`. Inspect the `RetryFeedbackPart`s, and compare `retries={'output': 0}` with `retries={'output': 2}`.
5. **Persistent chat CLI.** Build a REPL that saves a `Conversation` with `ConversationTypeAdapter` or `InMemoryConversationStore`. Resume it after a restart, fork with `conversation_id='new'`, and enforce one `cost_limit` across the whole conversation.
6. **Interrupt and resume.** Hit `request_limit=3` inside `capture_run_messages`, then resume with no prompt. Add a timer-driven `CancellationToken`, a run `timeout=`, and `ctx.remaining_time()` in a tool.
7. **Hooks observability.** Write a `Hooks` capability that:
   - logs each request;
   - audits `send_email`;
   - converts errors to `ToolFailed`/`ModelRetry`;
   - emits a `CustomEvent` that an `@agent.on_event` listener collects.
8. **History lab.** Script a 20-turn conversation with `FunctionModel`. Add `ProcessHistory` processors: keep the last N, and summarize the rest into a `CompactionPart`. Assert what the model received. Then break a tool-call pair on purpose and check `repair_messages()`.
9. **Mini-RAG with citations.** Embed local docs with a `sentence-transformers:` `Embedder`, search in memory, and expose a `retrieve` tool. Add `Citations()` with document input, and score it with a small Pydantic Evals dataset.
10. **Spec and batch pipeline.** Write a YAML triage agent with `BatchModelRequests` and load it with `Agent.from_file`. Submit 20 tickets with `PendingModelResponse`, then collect the results in a second script. Test it offline with `TestModel`.

## 4. Key takeaways

- **Agents and runs.** An `Agent[Deps, Output]` is a reusable typed container, and a run is a graph loop. `RunContext` is your single handle into the run: deps, usage, retries, deadline, `emit`, `enqueue` and `cancel`.
- **Instructions over system prompts.** Prefer `instructions`. Use `on_change='append'` for state that changes during a conversation, so the prompt cache survives. Never put untrusted text in instructions.
- **The output type is the contract.** Pick the output mode per model, validate with `@output_validator` + `ModelRetry`, and guard side effects with `ctx.partial_output` when streaming.
- **V2 conversations.** Pass `conversation=`, not just `message_history`, so usage, IDs and pending approvals travel together. Sanitize any history that comes from a client.
- **Separate budgets.** Retries, timeouts, usage limits and cancellation each have their own budget, and retry layers multiply. Every failure still leaves resumable `state='interrupted'` history.
- **Capabilities replaced V1 kwargs.** `ProcessHistory`, `Hooks`, `RetryOnModelErrors`, `ModelFallback`, `BatchModelRequests`, `Citations` and `Caching` cover what V1 configured with kwargs. YAML specs can declare the serializable ones.
- **Learn and test offline.** Start with `'test'`, `TestModel`/`FunctionModel`, `override` and `ALLOW_MODEL_REQUESTS=False`. Then judge quality with evals and traces.
- **One model layer, many APIs.** The same layer serves `direct.model_request*`, `ImageGenerator`, `Embedder` and the batch APIs.
