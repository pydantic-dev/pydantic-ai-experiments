# 06 — Pydantic AI example projects

Scope: `examples/pydantic_ai_examples/` (main, v2.71) and `docs/examples/*.md`. The package is also published on PyPI as `pydantic-ai-examples`.

**Patterns used across the examples**
- Nearly every text agent is created with `capabilities=[Caching()]`, which turns on prompt caching.
- Most files call `logfire.configure(send_to_logfire='if-token-present')` + `logfire.instrument_pydantic_ai()`. Logfire is optional: without a token nothing is sent.
- Model strings are hard-coded per file, mostly `openai:gpt-5.2` / `openai:gpt-5-mini`. Only `pydantic_model.py` reads `PYDANTIC_AI_MODEL`.

## 1. How to run them

From `docs/examples/setup.md` (`python/uv-run` is the docs' shorthand for "`python` or `uv run`"):

```bash
pip/uv-add "pydantic-ai[examples]"        # if installed from PyPI
uv sync --extra examples                  # if you cloned the repo
export OPENAI_API_KEY=...                 # most examples
export GEMINI_API_KEY=...                 # Gemini ones (provider prefers GOOGLE_API_KEY, falls back to GEMINI_API_KEY)
python/uv-run -m pydantic_ai_examples.<example_module_name>
OPENAI_API_KEY='...' uv run --with "pydantic-ai[examples]" -m pydantic_ai_examples.pydantic_model   # zero-setup
python/uv-run -m pydantic_ai_examples --copy-to examples/   # copy to edit
```

**Gotcha:** `--copy-to` runs `glob('*.*')`, so it copies only top-level files. The sub-packages (`ag_ui/`, `evals/`, `realtime_camera/`, `realtime_webrtc/`, `slack_lead_qualifier/`) are skipped.

| Example(s) | Run (`-m pydantic_ai_examples.` + …) | Keys / services |
|---|---|---|
| pydantic_model, weather_agent(_gradio), bank_support, stream_whales, chat_app (:8000), cancel_and_resume, flight_booking, medical_agent_delegation, data_analyst | module name | OpenAI only. Weather tools use keyless demo endpoints; data_analyst downloads a public Hugging Face dataset |
| roulette_wheel | `roulette_wheel` | Groq |
| stream_markdown | `stream_markdown` | Any of `GEMINI_API_KEY` / `OPENAI_API_KEY` / `GROQ_API_KEY` (missing ones are skipped) |
| sql_gen | `sql_gen "find me errors"` | Gemini + `docker run --rm -e POSTGRES_PASSWORD=postgres -p 54320:5432 postgres` |
| rag | `rag build`, then `rag search "…"` | OpenAI (about 300 embedding calls) + `pgvector/pgvector:pg17` on :54320 |
| twelvelabs_video_agent | module name | `TWELVELABS_API_KEY` (free tier) + OpenAI; optional `VIDEO_URL` |
| evals | `evals.example_03_unit_testing` (01–04) | OpenAI |
| slack_lead_qualifier | `python/uv-run -m modal serve -m pydantic_ai_examples.slack_lead_qualifier.modal` | Modal + secrets `slack`/`logfire`/`openai`, a Slack app |
| ag_ui | `ag_ui` (:9000) | OpenAI + AG-UI Dojo (clone ag-ui, `pnpm i`, `pnpm build --projects=demo-viewer`, `apps/dojo: pnpm dev`, open :3000/pydantic-ai) |
| realtime_text_to_audio / realtime_handoff | module name | OpenAI realtime; no mic needed |
| realtime_voice | module name | OpenAI realtime + PortAudio (`apt install libportaudio2`) + mic/speakers |
| realtime_webrtc | `uv run --all-packages uvicorn pydantic_ai_examples.realtime_webrtc.app:app` | OpenAI (or Azure via `WEBRTC_REALTIME_MODEL=azure:<deployment>` + `AZURE_OPENAI_*`) in repo-root `.env`; browser |
| realtime_camera | `realtime_camera.app` | Gemini Live by default (`GOOGLE_API_KEY`); OpenAI/Azure selectable; browser camera + mic |

**Without a paid key**
- **No key at all:** `docs/examples/cancellation.md` has a snippet that drives the example's `stream_turn` with `Agent(FunctionModel(stream_function=...))`, so it runs fully offline. The same approach (`FunctionModel` / `TestModel`, or a temporary `agent.override(model=TestModel())`) lets you check any example's tool wiring without a key.
- **Free-tier providers** (check current terms):
  - Gemini: `sql_gen` (default; Postgres runs locally), `stream_markdown`, `pydantic_model` with `PYDANTIC_AI_MODEL=google:…`, and `realtime_camera` (Gemini Live; its drawing agent defaults to `google:gemini-3.5-flash`).
  - Groq: `roulette_wheel` and `stream_markdown`.
- **Everything else:** edit the hard-coded model string to switch provider.

## 2. Examples

### pydantic_model
**What it builds:** Turns "The windy city in the US of A." into `MyModel(city, country)` and prints the output and the token usage.
**Features:** `Agent(model, output_type=MyModel)`, `run_sync`, `result.output`, `result.usage`, model from an env var.
```python
model = os.getenv('PYDANTIC_AI_MODEL', 'openai:gpt-5.2')
print(f'Using model: {model}')
agent = Agent(model, output_type=MyModel, capabilities=[Caching()])

if __name__ == '__main__':
    result = agent.run_sync('The windy city in the US of A.')
    print(result.output)
```
**Ideas:** an address or contact extractor; an invoice-to-JSON parser; a CSV-row normaliser. **Difficulty:** beginner.

### weather_agent (+ weather_agent_gradio)
**What it builds:** An agent that chains `get_lat_lng` → `get_weather` (with an `httpx.AsyncClient` in deps) to answer weather questions about several places. The Gradio file adds a chat UI that shows tool calls and results, plus retry and undo.
**Features:** `deps_type=Deps`, `@agent.tool` + `RunContext[Deps]`, docstring `Args:` used as tool descriptions, `retries=2`, a tool returning a `BaseModel`. The Gradio version adds `run_stream(..., message_history=)`, `new_messages()`, `ToolCallPart.args_as_json_str()`, `ToolReturnPart` and `stream_text()`.
```python
@weather_agent.tool
async def get_lat_lng(ctx: RunContext[Deps], location_description: str) -> LatLng:
    # ... docstring with Args:
    r = await ctx.deps.client.get(
        'https://demo-endpoints.pydantic.workers.dev/latlng',
        params={'location': location_description},
    )
    r.raise_for_status()
    return LatLng.model_validate_json(r.content)
```
**Ideas:** swap in a real weather API; a trip-packing assistant; any multi-step lookup chain. **Difficulty:** beginner.

### bank_support
**What it builds:** A support agent that greets the customer by name (dynamic instructions), checks their balance with a tool, and returns `SupportOutput(support_advice, block_card, risk)`.
**Features:** a dataclass passed as `deps_type`, `output_type` with field docstrings, async `@agent.instructions`, `@agent.tool`.
```python
@support_agent.instructions
async def add_customer_name(ctx: RunContext[SupportDependencies]) -> str:
    customer_name = await ctx.deps.db.customer_name(id=ctx.deps.customer_id)
    return f"The customer's name is {customer_name!r}"
```
**Ideas:** a helpdesk bot that flags escalations; account-aware SaaS support; fraud-risk scoring. **Difficulty:** beginner.

### roulette_wheel (no docs page; `docs/agent.md` shows a variant)
**What it builds:** A toy game. The winning number lives in deps, a tool checks the bet, and the output is a `bool`.
**Features:** `output_type=bool`, `retries=3`, a `Literal['winner', 'loser']` tool return, `run_stream` + `get_output()`, a Groq model.
```python
    async with roulette_agent.run_stream(
        'Put my money on square eighteen', deps=deps
    ) as response:
        result = await response.get_output()
```
**Ideas:** yes/no classifiers backed by deterministic tools; policy checks; quiz grading. **Difficulty:** beginner.

### stream_markdown
**What it builds:** Streams a Markdown answer, rendered live in the terminal with `rich`, once for each provider whose key is set.
**Features:** an `Agent(capabilities=[Caching()])` with no default model, per-run `run_stream(prompt, model=model)`, `stream_output()`, `KnownModelName`.
```python
            with Live('', console=console, vertical_overflow='visible') as live:
                async with agent.run_stream(prompt, model=model) as result:
                    async for message in result.stream_output():
                        live.update(Markdown(message))
```
**Ideas:** a terminal "ask" CLI; side-by-side model comparison. **Difficulty:** beginner.

### stream_whales
**What it builds:** Streams `list[Whale]` structured output and redraws a `rich` table as partial records validate.
**Features:** a `TypedDict` output whose fields are `NotRequired` (this is what lets partial objects validate), `Field(description=, ge=50)`, `stream_output(debounce_by=0.01)`.
```python
    weight: NotRequired[
        Annotated[
            float,
            Field(description='Average weight of an adult whale in kilograms.', ge=50),
        ]
    ]
# ...
agent = Agent('openai:gpt-5.2', output_type=list[Whale], capabilities=[Caching()])
# ...
            async for whales in result.stream_output(debounce_by=0.01):
```
**Ideas:** progressive search-result cards; live-filling forms or comparison grids. **Difficulty:** beginner–intermediate.

### chat_app (`.py` + `.html` + `.ts` transpiled in the browser)
**What it builds:** A FastAPI chat app that streams newline-delimited JSON to the browser and stores the full message history in SQLite between requests.
**Features:** `run_stream(prompt, message_history=)`, `new_messages_json()`, `ModelMessagesTypeAdapter.validate_json`, `ModelResponse`/`TextPart`/`UserPromptPart`, `logfire.instrument_fastapi`.
```python
        async with agent.run_stream(prompt, message_history=messages) as result:
            async for text in result.stream_output(debounce_by=0.01):
                m = ModelResponse(parts=[TextPart(text)], timestamp=result.timestamp)
                yield json.dumps(to_chat_message(m)).encode('utf-8') + b'\n'
        await database.add_messages(result.new_messages_json())
```
(comments trimmed) **Ideas:** a multi-user chat keyed by conversation id; an internal assistant on Postgres; an SSE variant. **Difficulty:** intermediate.

### cancel_and_resume
**What it builds:** A prompt_toolkit terminal chat. Esc or Ctrl-C cancels the streaming reply, and the next prompt resumes from the history kept up to that point.
**Features:** `CancellationToken` (single-use: one per turn), `run_stream(..., cancellation_token=)`, `stream_text(delta=True)`, `RunCancelled.all_messages()`. Interrupted tool calls are repaired automatically on the next run.
```python
    try:
        async with agent.run_stream(
            prompt, message_history=history, cancellation_token=token
        ) as result:
            async for delta in result.stream_text(delta=True):
                on_text(delta)
        return result.all_messages(), False
    except RunCancelled as exc:
        return exc.all_messages(), True
```
**Ideas:** a "Stop generating" button; a supervisor that kills runaway runs but keeps partial work. **Difficulty:** intermediate.

### flight_booking
**What it builds:** A CLI multi-agent flow:
1. `search_agent` delegates flight extraction to `extraction_agent`.
2. An output validator enforces the requested route and date.
3. A human confirms the flight or asks to keep searching.
4. `seat_preference_agent` parses the seat choice.

**Features:** agent-in-a-tool delegation with `usage=ctx.usage`, union outputs (`FlightDetails | NoFlightFound`), `@output_validator` + `ModelRetry`, `UsageLimits(request_limit=15)` + a shared `RunUsage()`, `all_messages(output_tool_return_content=...)` to continue a search, `Agent[Deps, Out]` generics.
```python
@search_agent.tool
async def extract_flights(ctx: RunContext[Deps]) -> list[FlightDetails]:
    """Get details of all flights."""
    # we pass the usage to the search agent so requests within this agent are counted
    result = await extraction_agent.run(ctx.deps.web_page_text, usage=ctx.usage)
```
**Ideas:** hotel or rental search with hard constraints; quote comparison with human approval. **Difficulty:** intermediate–advanced.

### medical_agent_delegation
**What it builds:** A `triage_agent` orchestrator calls `consult_specialist` (GP, cardiology or neurology agents returning `MedicalReport`) or `consult_senior_doctor` (`TreatmentPlan`) and returns `TriageFinalOutput`.
**Features:** agents as tools via a `SPECIALIST_MAP`, an `Enum` tool argument, shared deps passed down (`deps=ctx.deps`), nested structured outputs, a `ModelHTTPError` fallback, escalation rules in the instructions. Unlike flight_booking, it does **not** pass `usage=ctx.usage` to the sub-agents; adding it is a good exercise.
```python
    specialist_agent = SPECIALIST_MAP.get(specialty)
    # ...
    result = await specialist_agent.run(f'Consultation: {question}', deps=ctx.deps)
    report: MedicalReport = result.output
```
**Ideas:** IT-incident routing with on-call escalation; legal intake; L1/L2 support tiers. **Difficulty:** intermediate.

### sql_gen
**What it builds:** Text-to-SQL for a log `records` table. The prompt includes the schema and few-shot examples, and the output is validated by running `EXPLAIN` on Postgres.
**Features:** `output_type=Success | InvalidRequest`, `@agent.instructions`, `format_as_xml(SQL_EXAMPLES)`, `@agent.output_validator` + `ModelRetry`, asyncpg in deps, Gemini.
```python
    if not output.sql_query.upper().startswith('SELECT'):
        raise ModelRetry('Please create a SELECT query')
    try:
        await ctx.deps.conn.execute(f'EXPLAIN {output.sql_query}')
    except asyncpg.exceptions.PostgresError as e:
        raise ModelRetry(f'Invalid query: {e}') from e
```
**Ideas:** an NL query box over analytics data (use a read-only role); log search; generate-then-validate for any DSL. **Difficulty:** intermediate.

### data_analyst
**What it builds:** Loads a Hugging Face dataset into pandas and answers questions with DuckDB SQL. DataFrames stay in deps; the LLM sees only references like `Out[1]`.
**Features:** deps used as a mutable variable store, sync tools, `ModelRetry` raised from tools and deps helpers.
```python
    data = ctx.deps.get(dataset)
    result = duckdb.query_df(df=data, virtual_table_name='dataset', sql_query=sql)
    # pass the result as ref (because DuckDB SQL can select many rows, creating another huge dataframe)
    ref = ctx.deps.store(result.df())
    return f'Executed SQL, result is `{ref}`'
```
**Ideas:** a CSV/Parquet analyst; a spreadsheet Q&A bot; pass-by-handle for big artifacts. **Difficulty:** intermediate.

### rag
**What it builds:** Q&A over a Logfire-docs snapshot:
- `build` embeds each section into pgvector (`text-embedding-3-small`, `vector(1536)`, HNSW index), calling the OpenAI SDK directly.
- `search` runs an agent with a `retrieve` tool.

**Features:** `AsyncOpenAI` + `asyncpg.Pool` in deps, a retrieval tool, `logfire.span`, concurrent ingestion with an anyio task group and a semaphore.
```python
    rows = await context.deps.pool.fetch(
        'SELECT url, title, content FROM doc_sections ORDER BY embedding <-> $1 LIMIT 8',
        embedding_json,
    )
```
**Ideas:** RAG over your own wiki or KB, with cited URLs; code search. **Difficulty:** intermediate.

### twelvelabs_video_agent
**What it builds:** An agent that answers questions about a video URL by having its `analyze_video` tool query the TwelveLabs Pegasus model.
**Features:** a third-party multimodal API wrapped as a tool, an async SDK client in deps, `retries=2`.
```python
    response = await ctx.deps.twelvelabs.analyze(
        model_name='pegasus1.5',
        video=VideoContext_Url(url=ctx.deps.video_url),
        prompt=prompt,
        max_tokens=2048,
    )
```
**Ideas:** meeting or lecture Q&A; camera-footage search; wrapping any specialist API such as OCR or speech-to-text. **Difficulty:** beginner–intermediate.

### evals/ (no docs/examples page)
**What it builds:** A full `pydantic_evals` loop for a `time_range_agent` ("logs from 2 hours ago" → `TimeRangeBuilderSuccess | TimeRangeBuilderError`):
- `01` uses an LLM to generate a YAML dataset, and **overwrites** the committed v1.
- `02` adds custom evaluators and writes v2.
- `03` is a unit test that requires a pass rate above 90%.
- `04` compares models.

**Features:** `generate_dataset`, `Dataset.from_file`/`to_file(custom_evaluator_types=)`, `IsInstance`/`LLMJudge` declared in YAML, custom `Evaluator` subclasses, a span-tree evaluator (`ctx.span_tree.any(SpanQuery(...))` that asserts a tool was called), `add_evaluator(specific_case=)`, `evaluate_sync`, `report.averages().assertions`, `agent.override(model=)` for A/B runs, and `now` passed in deps for determinism.
```python
    dataset = Dataset[TimeRangeInputs, TimeRangeResponse, NoneType].from_file(
        dataset_path, custom_evaluator_types=CUSTOM_EVALUATOR_TYPES
    )
    report = dataset.evaluate_sync(infer_time_range)
    print(report)
```
**Ideas:** a CI regression gate for any agent; a model bake-off on cost vs quality; tool-usage audits. **Difficulty:** intermediate–advanced.

### slack_lead_qualifier (`slack-lead-qualifier.md` is a step-by-step tutorial)
**What it builds:** A Modal app. A `team_join` webhook triggers an agent that researches the new member with DuckDuckGo and returns `Analysis | None`, which is posted to `#new-slack-leads`. A daily cron posts the top 5.
**Features:**
- Agent: `tools=[duckduckgo_search_tool()]`, `NativeOutput([Analysis, NoneType])`, `format_as_xml(..., root_tag=)`, `Annotated[int, Ge(1), Le(5)]`.
- Observability: `@logfire.instrument`, plus distributed tracing via `get_context()`/`attach_context()`.
- Infrastructure: Modal `spawn` (because Slack expects a reply within 3 s), `modal.Cron`, `modal.Dict`.
```python
    tools=[duckduckgo_search_tool()],
    output_type=NativeOutput([Analysis, NoneType]),
# ... app.py:
    _process_slack_member.spawn(
        profile.model_dump(), logfire_ctx=get_context()
    )
```
**Ideas:** signup or stargazer enrichment for a CRM; a daily ticket digest ranked by urgency. You can test it with the doc's fake `curl` payload. **Difficulty:** advanced (mostly infrastructure).

### ag_ui (7 Starlette sub-apps mounted on :9000 for the AG-UI Dojo)
**What it builds:** One small agent per AG-UI feature:
- agentic chat: a server tool plus frontend tools;
- generative UI: tools return `StateSnapshotEvent`/`StateDeltaEvent` (JSON Patch);
- human-in-the-loop and tool-based UI: no backend code needed;
- predictive state: a `CustomEvent('PredictState')`;
- shared state: `StateDeps[RecipeSnapshot]`;
- tool approval: interrupts.

**Features:** `AGUIAdapter.dispatch_request(request, agent=, deps=)`, `@agent.tool_plain`, tools that return AG-UI events, state-aware `@agent.instructions`, `replace(deps)` per request, `requires_approval=True` + `output_type=[str, DeferredToolRequests]`.
```python
agent = Agent(
    'openai:gpt-5-mini',
    output_type=[str, DeferredToolRequests],
    capabilities=[Caching()],
)

@agent.tool_plain(requires_approval=True)
def delete_file(path: str) -> str:
    """Delete a file. The run pauses here and waits for the user to approve before executing."""
    # Real implementation would actually delete the file.
    return f'deleted {path}'
```
**Ideas:** a CopilotKit/React copilot that edits shared state; approval-gated admin actions; live plan trackers. **Difficulty:** intermediate (most of the effort is the frontend setup).

### realtime_text_to_audio
**What it builds:** The smallest realtime session. You send text, hear the spoken reply with a streamed transcript, and get a 24 kHz WAV file.
**Features:** `agent.realtime('openai:gpt-realtime', model_settings=OpenAIRealtimeModelSettings(openai_voice='marin')).session()`, `session.send()`, `match` on `PartDeltaEvent(delta=SpeechPartDelta())` (`audio_chunk`, `transcript_delta`), `RealtimeTurnCompleteEvent`.
```python
        async for event in session:
            match event:
                case PartDeltaEvent(delta=SpeechPartDelta() as delta):
                    if delta.audio_chunk:
                        audio.extend(delta.audio_chunk)
                    if delta.transcript_delta:
                        print(delta.transcript_delta, end='', flush=True)
                case RealtimeTurnCompleteEvent():
                    break
```
(comments trimmed) **Ideas:** IVR or voicemail prompt generation; a text chatbot that speaks. **Difficulty:** beginner–intermediate.

### realtime_voice
**What it builds:** A full-duplex microphone/speaker assistant with a `get_weather` tool, a live transcript, and barge-in.
**Features:** `session(handle_barge_in=True)`, `send_audio(mic)` (takes an async iterator), `stream_audio()` (bounded buffer), `audio_input_sample_rate`/`audio_output_sample_rate`, `FunctionToolCallEvent`/`FunctionToolResultEvent`, `PartEndEvent(part=SpeechPart())`, `listentome` for audio I/O.
```python
    async with mic, speaker, anyio.create_task_group() as tg:
        tg.start_soon(session.send_audio, mic)
        model_audio = session.stream_audio()
# ... main():
    async with realtime.session(handle_barge_in=True) as session:
```
**Ideas:** a hands-free workshop or kitchen helper; a voice front-end for an existing tool agent. **Difficulty:** intermediate.

### realtime_handoff
**What it builds:** A realtime voice agent runs a support call (caller turns are scripted as text, so no mic is needed). Then `session.all_messages()` is handed to a text agent with `output_type=SupportTicket`, because realtime models can't produce structured output.
**Features:** realtime and text runs share the same `ModelMessage` history; turns are driven on `RealtimeTurnCompleteEvent`; a `for/else` guard catches early disconnects.
```python
        handoff_history = session.all_messages()

    ticket = await triage_agent.run(
        'Create the support ticket for this call.', message_history=handoff_history
    )
```
**Ideas:** after-call summaries into a CRM; voice intake forms; voice order-taking. **Difficulty:** intermediate.

### realtime_webrtc
**What it builds:** A browser voice agent. Audio flows browser ↔ OpenAI/Azure **directly over WebRTC**. A FastAPI backend relays the SDP offer (so the key stays server-side) and attaches a **sideband** session by `call_id` that runs the tools and records history.
**Features:** `infer_realtime_model` (choice via env var, Azure supported), `realtime.answer_webrtc_offer(sdp)` → `.sdp`/`.session` (`WebRTCSession`), `realtime.session(provider_session=)`, handling of attach timeouts and disconnects. Sideband sessions have no `send_audio`.
```python
    answer = await realtime.answer_webrtc_offer(sdp_offer)
    call = Call(answer_sdp=answer.sdp, provider_session=answer.session)
# ... run_sideband():
        async with realtime.session(provider_session=call.provider_session) as session:
```
**Ideas:** a website voice concierge; phone access over HTTPS with `cloudflared`; voice-driven internal tools. **Difficulty:** advanced.

### realtime_camera (610-line server + `index.html`)
**What it builds:** A provider-agnostic camera and voice assistant over a WebSocket bridge. Mic PCM, one JPEG frame per second, and text go in; audio, transcripts and citation chips come out. It also has a **Watch** mode for proactive narration, native **web search**, and a **sketch redraw** tool that delegates to a second Agent producing sandboxed HTML.
**Features:**
- Model setup: `infer_realtime_model`; `GoogleRealtimeModel(..., provider='google-cloud')` for Vertex; `RealtimeModelSettings(output_modality=, reconnect=ReconnectPolicy(max_attempts=5))`.
- Provider settings: `GoogleRealtimeModelSettings` (proactive audio, affective dialog, `AutomaticVAD`, turn coverage) and `OpenAIRealtimeModelSettings` + `TurnDetection`.
- Inputs and tools: `BinaryContent` image frames via `session.send`; the `WebSearch()` capability, enabled only when `model.profile['supported_native_tools']` includes it.
- Events: `NativeToolReturnPart` for citations; `RealtimeInputSpeechStartEvent`/`RealtimeResponseInterruptedEvent` for barge-in.
- Cancellation: tool cancellation handled via `anyio.get_cancelled_exc_class()` with shielded cleanup.
- Security: a WebSocket origin guard.
```python
                    if isinstance(chunk := message.get('bytes'), bytes):
                        await session.send_audio(chunk)
                    elif isinstance(text := message.get('text'), str):
                        await _dispatch_text(session, text)
# ... ws():
        async with agent.realtime(
            model, deps=CameraDeps(emit=emit)
        ).session() as session:
```
**Ideas:** assistive "what am I looking at" vision; whiteboard-to-diagram capture; a hands-on repair or cooking coach. Keep it local: it has no authentication. **Difficulty:** advanced.

## 3. Feature → example matrix

Column key: pm=pydantic_model, wx=weather(+gradio), bank, rl=roulette, md=stream_markdown, wh=stream_whales, chat, cx=cancel_and_resume, fl=flight_booking, med=medical, sql, da=data_analyst, rag, tl=twelvelabs, ev=evals, sl=slack, ag=ag_ui, t2a/vo/ho/rtc/cam = realtime text_to_audio/voice/handoff/webrtc/camera. `x` = core feature, `~` = partial.

| Feature | pm | wx | bank | rl | md | wh | chat | cx | fl | med | sql | da | rag | tl | ev | sl | ag | t2a | vo | ho | rtc | cam |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Structured output | x | | x | x | | x | | | x | x | x | | | | x | x | x | | | x | | |
| Union / None / NativeOutput / deferred | | | | | | | | | x | | x | | | | x | x | x | | | | | |
| Function tools | | x | x | x | | | | | x | x | | x | x | x | x | ~ | x | | x | | x | x |
| Deps / RunContext | | x | x | x | | | | | x | x | x | x | x | x | x | | x | | | | | x |
| Dynamic instructions | | | x | | | | | | | | x | | | | | | x | | | | | ~ |
| Output validator / ModelRetry | | | | | | | | | x | | x | x | | | | | | | | | | |
| Streaming text | | ~ | | | x | | x | x | | | | | | | | | | ~ | | | | |
| Streaming structured | | | | ~ | | x | | | | | | | | | | | | | | | | |
| Message history | | ~ | | | | | x | x | x | | | | | | | | | | | x | | |
| Multi-agent | | | | | | | | | x | x | | | | | | | | | | x | | x |
| Usage / UsageLimits | ~ | | | | ~ | | | | x | | | | | | | | | | | | | |
| Graphs (pydantic_graph) | | | | | | | | | | | | | | | | | | | | | | |
| RAG / retrieval / search | | | | | | | | | | | | ~ | x | | | ~ | | | | | | ~ |
| Evals | | | | | | | | | | | | | | | x | | | | | | | |
| Web UI / server | | x | | | | | x | | | | | | | | | x | x | | | | x | x |
| AG-UI | | | | | | | | | | | | | | | | | x | | | | | |
| Realtime / voice | | | | | | | | | | | | | | | | | | x | x | x | x | x |
| Human-in-the-loop / approval | | | | | | | | ~ | x | | | | | | | | x | | | | | |
| Cancellation (durable exec: none) | | | | | | | | x | | | | | | | | | | | | | | ~ |
| Native/prebuilt tools | | | | | | | | | | | | | | | | x | | | | | | x |
| Multimodal | | | | | | | | | | | | | | x | | | | x | x | x | x | x |
| Model switching | x | | | | x | | | | | | | | | | x | | | | | | x | x |
| Deployment / cron | | | | | | | | | | | | | | | | x | | | | | | |

**Not covered by any example** (use the feature docs):
- `pydantic_graph`. The old `question_graph` example is gone, and `docs/navigation.yml` now redirects `examples/question-graph` to the setup page.
- Durable execution (Temporal/DBOS/Prefect).
- MCP (installed by the extra but unused).
- `FallbackModel` and `agent.iter()`.
- Pydantic AI embeddings (rag calls the OpenAI SDK directly).

## 4. Suggested learning path

1. **Core loop:** `pydantic_model` → `bank_support` → `weather_agent` → `roulette_wheel`. This covers output types, static and dynamic instructions, tools, deps and retries with minimal surface area. Turn on Logfire early to *see* tool calls.
2. **Streaming and conversations:** `stream_markdown` → `stream_whales` (partial validation via `NotRequired`) → `chat_app` (history serialisation) → `weather_agent_gradio` → `cancel_and_resume`. Run the `FunctionModel` docs snippet to learn offline testing at the same time.
3. **Reliability and grounding:** `sql_gen` (validators + `ModelRetry` against a real system) → `data_analyst` (deps as a scratchpad) → `rag` → `twelvelabs_video_agent`.
4. **Multi-agent:** `flight_booking` (delegation, usage propagation, `UsageLimits`, hand-off, human in the loop) → `medical_agent_delegation` (router orchestration; add the missing `usage=ctx.usage`).
5. **Quality:** `evals/` 03 → 02 → 04 → 01. Run 01 last, because it overwrites the committed v1 dataset.
6. **Frontends:** `ag_ui`, in the order agentic_chat → shared_state → tool_approval (deferred tools become UI interrupts).
7. **Shipping:** `slack_lead_qualifier` (webhook → background job → cron, `NativeOutput`, tracing).
8. **Realtime:** text_to_audio → handoff → voice → webrtc → camera.
9. **Fill the gaps yourself:** rebuild `flight_booking` as a graph; add `FallbackModel` to `chat_app`; expose `bank_support` tools over MCP.

**Doc/code mismatches and quirks**
- `weather-agent.md` still asks for `WEATHER_API_KEY`/`GEO_API_KEY`; the code uses keyless demo endpoints that return random data.
- `bank-support.md` suggests `PYDANTIC_AI_MODEL`, but the code hard-codes `openai:gpt-5.2`.
- In `bank_support.py`, the `DatabaseConn` methods use a module-global `cur` (defined only under `__main__`) instead of `self.sqlite_conn`. Fix this before reusing the class.
- The slack doc says `openai:gpt-5`; the code uses `gpt-5.2`.
- The `realtime_webrtc/README.md` diagram says `realtime_session(...)`; the code calls `realtime.session(...)`.
- `stream_markdown.py` lists `google:gemini-3.8-flash` and `openai:gpt-6-luna`; `evals/example_01` uses `openai:gpt-6.1-sol`.
- CI only smoke-imports the top-level `*.py` files (`tests/import_examples.py`, with fake keys). `tests/test_realtime_examples.py` covers voice barge-in and the camera origin guard.
