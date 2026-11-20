# Pydantic AI learning: handover

Where we are, what's here, and what comes next. Written 2026-11-20, for continuing on the machine that has the Postgres database.

## Quick start on the new machine

```bash
git clone https://github.com/pydantic-dev/pydantic-ai-experiments.git
cd pydantic-ai-experiments
git checkout learning

python3 -m venv .venv
.venv/bin/pip install -r learning/requirements.txt

cp learning/.env.example .env          # then put your Anthropic key in it (.env is gitignored)
set -a; . ./.env; set +a               # load the key into the shell, each new terminal

PYDANTIC_AI_NO_BANNER=1 .venv/bin/python learning/scripts/first_agent_trace.py
```

`MODEL=test` in front of `first_agent_trace.py` runs it offline, free, with no API key.

The API key is **not** in the repo. It lived only in `/home/ubuntu/pydantic-dev/.env` on the old machine. That key was pasted into a chat, so consider creating a fresh one in the Anthropic Console for the new machine.

## What's in `learning/`

| Path | What it is |
|---|---|
| `notes/01-core.md` … `06-examples.md` | Six research notes (~230 KB) from the Pydantic AI docs and examples at v2.71. Each feature: what it is, when to use it, a verified example, gotchas, and the doc path. Each note ends with experiment ideas. |
| `deck/project/` | The 37-slide "Pydantic AI Field Guide": `deck.json` gives the order, plus `deck.css` and `slides/*.html`, with speaker notes in `<aside>` |
| `publish/build.py` | Builds the static site (slides with notes, and the notes as HTML and .md): `python learning/publish/build.py <outdir>`. Needs `markdown`. |
| `scripts/first_agent_trace.py` | The roulette agent, printing each step of the run and every message. Opus by default; `MODEL=test` runs it offline. |
| `scripts/wire_capture.py` | Shows the exact HTTP request bodies Pydantic AI would send to Anthropic and OpenAI, with no key and no network |
| `scripts/show_prompt.py` | The same as above, but on a real Opus run: prints every request sent to the API |
| `scripts/cache_demo.py` | The same agent with and without `Caching()`. Measured: $0.22 without, $0.08 with (63% cheaper). |
| `scripts/mcp_demo/` | A tiny stdio MCP server (`casino_server.py`) and an Opus agent that uses it (`agent_with_mcp.py`) |

The deck is also published:
- **Unlisted website:** https://pydantic-dev.arkiv-global.net/fg-497f596c0c67a1f6/ (nginx and certbot on the old machine; files in `/var/www/pydantic-dev/`)
- **claude.ai Slides artifact:** https://claude.ai/artifact/MXgV5h6Udz81cpmhG96VvH

## What we learned (the core concepts, in order)

1. **A run is a loop.**
   - The steps go `UserPromptNode → ModelRequestNode → CallToolsNode → … → End`.
   - It ends when the model produces output that validates against `output_type`.
   - Each tool round is one more model request; `usage.requests` counts them.
2. **Tool calls.**
   - The model never runs code. It replies with a `ToolCallPart` (a name plus JSON arguments).
   - Pydantic AI validates the arguments, runs your function and sends back a `ToolReturnPart`.
   - If validation fails or the tool raises `ModelRetry`, the error goes back to the model and it tries again.
3. **How tools are described to the model.**
   - Function name → `name`.
   - Docstring → `description`. The `Args:` section becomes per-parameter descriptions.
   - Type hints, `Literal` and `Field(...)` become the JSON schema.
   - `RunContext` is hidden from the model, and so is `deps`, which never reaches the model.
   - Docstrings are prompts, and types are guardrails.
4. **The trip to a real model.**
   - Pydantic AI converts tools into each provider's `tools` field (OpenAI `function`/`parameters`, Anthropic `input_schema`).
   - The provider turns that into prompt text, which is why a tiny prompt cost 1,221 input tokens.
   - The model was trained to write tool calls; the provider parses them back into JSON.
5. **Structured output.**
   - Models with native structured output (Claude Opus 5.5) receive `output_config` with a JSON schema and answer with JSON text.
   - Other models get a hidden `final_result` tool. TestModel and OpenAI Chat use this.
   - Pydantic AI picks the method from the model profile.
6. **The model has no memory between requests.**
   - Every request re-sends the system instructions, the tools and the whole conversation.
   - That's why cost grows per turn and why `message_history=` exists.
7. **Caching is off by default.**
   - Add `capabilities=[Caching()]`. Anthropic caches nothing unless asked.
   - The first write costs 1.25×, reads cost 0.1×, the cache lasts 5 minutes (`retention='1h'` for longer), and there's a minimum prompt length.
   - Keep the beginning of the prompt (tools, instructions) fixed.
8. **Seeing the prompt.**
   - `result.all_messages()` doesn't include the tool definitions.
   - `capture_run_messages()` works even when a run raises.
   - An httpx2 `event_hooks` client gives the raw request bodies (see `show_prompt.py`).
   - Logfire with `instrument_pydantic_ai()` and `instrument_httpx(capture_all=True)` gives the full visual trace.
   - The provider's internal rendering can't be seen.
9. **MCP.**
   - `MCPToolset` connects when the run starts, then lists the server's tools (`tools/list`, cached).
   - Those tools look like any other tool to the model, and the model decides when to call them.
   - Each call is an MCP `tools/call`.
   - Server *instructions* are injected into the prompt, and they changed Opus's behaviour in the demo, so only trust servers you know.
   - Resources and prompts are **not** sent to the model automatically.
   - Use `.prefixed()`, `.filtered()` and `.approval_required()` to control what the model gets.

v2 tip: much older online code is v1. See the "v2-traps" slide and `docs/migration.md`: `result_type` → `output_type`, `MCPServerStdio` → `MCPToolset`, kwargs → capabilities.

## Budget and model

- About $195 of Anthropic credit; Opus 5.5 (`anthropic:claude-opus-5-5`) is fine for learning.
- Measured costs:
  - roulette agent: ~$0.006 per run
  - MCP demo: ~$0.016
  - cache demo: ~$0.31 for both runs together
- Always read `result.usage.cost`.

## Next project: the daily financial report (Postgres)

### The agreed design: SQL produces the numbers, the agent explains them

```
Postgres ──fixed SQL──► Facts (Pydantic) ──► Agent (Opus) ──► Narrative (Pydantic)
   ▲                                          │ tools: drill_down, compare_periods
   └──── read-only, allowlisted queries ◄─────┘
Renderer (Jinja → HTML/PDF): numbers from Facts, words from Narrative
```

1. **Facts.**
   - The KPIs come from fixed, reviewed, tested SQL and are loaded into Pydantic models (`Facts`, `Kpi`, `ClientRow`, `InvoiceRow`).
   - The LLM never computes a figure and never writes free-form SQL for the daily run.
2. **Agent.**
   - `Agent(..., deps_type=Deps, output_type=Narrative, capabilities=[Caching()])`. `Deps` holds a read-only DB pool and today's `Facts`.
   - The facts are injected through `@agent.instructions`.
   - Tools such as `drill_down(kpi_id: Literal[...], group_by: Literal['client', 'product', 'region'])` run parameterised, allowlisted queries.
3. **Narrative model.**
   - `summary`, plus `findings: list[Finding]`.
   - Each `Finding` has `severity: Literal['info', 'watch', 'action']`, `headline`, `explanation`, `kpi_ids` and `client_ids`.
4. **Grounding.**
   - `@agent.output_validator` checks that every KPI id and client id exists and that quoted numbers match the facts.
   - If not, it raises `ModelRetry` and the model corrects itself.
5. **Rendering.** Tables and charts take values only from `Facts`.
6. **Daily schedule.**
   - A cron job or systemd timer runs: build facts → agent → render.
   - Store `Facts`, `Narrative` and the rendered output in Postgres for audit and day-to-day comparison.
   - Turn on Logfire.
7. **Evals.**
   - `pydantic_evals` on about 20 past days with known answers.
   - Score grounding (no invented numbers or clients), coverage (planted anomalies caught) and an LLM-as-judge quality score.
   - Re-run after any change to the prompt or the model.

### Two things to settle early

- **Client data goes to Anthropic.** Consider sending pseudonymous client IDs and putting real names back in only at render time. Check GDPR and contract obligations.
- **Use a read-only Postgres role** with `SELECT` on a few views only, and set `statement_timeout`.

### Where the agent adds value over a plain automated report

The plain report is better for the numbers; build it first regardless. The agent adds:
- explaining *why* KPIs moved (drill-downs);
- ranking what matters today;
- reading free text (invoice notes, dispute reasons, CRM comments);
- answering follow-up questions;
- versions of the commentary for each audience.

Rule of thumb: if someone currently spends time every day explaining the report, the agent can take over most of that. If nobody does, the report alone may be enough.

Suggested rollout:
1. Build the plain report.
2. Add the agent as a commentary layer.
3. Run it beside the human commentary for 2–3 weeks.
4. Keep it only if it saves analyst time or catches things people missed.

### Open questions (answer these to start building)

1. Does someone write commentary or investigate the numbers today?
2. Is there free text (notes, disputes, emails) that matters for the report?
3. The relevant part of the schema: DDL, or table and column names.
4. The 5–10 KPIs the daily report must show.
5. An example of a current report, even a rough one.

### Suggested first steps on the DB machine

1. Create the read-only role and a few `report_*` views.
2. Write `facts.py`: SQL for the 5–10 KPIs, returning a `Facts` model, with a test against a known day.
3. Write `report_agent.py` with the design above. Start with `MODEL=test` / `FunctionModel` to get the plumbing right, then switch to Opus.
4. Add the output validator, then the renderer, then evals.

## Other experiments from the deck (by difficulty)

1. Offline hello-agent.
2. Run-mode tour (`run`, `run_sync`, `run_stream`, `run_stream_events`, `iter`).
3. Retry lab (`ModelRetry` vs `ToolFailed`).
4. Approval CLI with deferred tools: save the conversation and resume in another process.
5. Persistent chat with `ConversationStore`.
6. Local MCP (done: `scripts/mcp_demo`).
7. A middleware capability.
8. First eval suite.
9. Parallel graph.
10. Safe coder with Harness.

Details are on the "experiments" slide and in the notes.
