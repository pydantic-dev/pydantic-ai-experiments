# 04: Multi-agent, Graphs, Durable Execution, Evals and Observability

Pydantic AI v2.71. I read the docs and checked uncertain APIs against `pydantic_ai_slim/`, `pydantic_graph/` and `pydantic_evals/`.

The docs write models as aliases. Here they are expanded from `docs/model_aliases/aliases.json`:
- `openai:medium` = `openai:gpt-6.1-sol`
- `openai:small` = `openai:gpt-6-luna`
- `google:medium` = `google:gemini-3.8-flash`

To experiment offline, use `pydantic_ai.models.test.TestModel` or `FunctionModel`.

---

## 1. Overview

`docs/multi-agent-applications.md` lays out a ladder, from simplest to most complex:

1. **Single agent.**
2. **Agent delegation.** A tool calls a child agent, then control returns to the parent.
3. **Programmatic hand-off.** Your code, or a human, picks the next agent.
4. **Graphs (`pydantic-graph`).** A typed state machine or dataflow. The docs warn against it: "don't use a nail gun unless you need a nail gun".
5. **Deep agents and durable execution.** Harness capabilities add planning, sub-agents and sandboxes. A durable engine such as Temporal, DBOS or Prefect keeps a run alive through crashes, deploys and waits of several days.

Evals and Logfire form the dev loop around every rung:
1. Instrument with OpenTelemetry.
2. Debug the traces in Logfire or any OTel backend.
3. Turn interesting cases into `pydantic_evals` datasets.
4. Gate changes with offline experiments, including span and trajectory checks on the same OTel spans.
5. Keep scoring production traffic with online evaluation, which emits `gen_ai.evaluation.result` events.

**V2 changes in this area** (`docs/migration.md`):
- `pydantic_graph.persistence` and `.mermaid` are **removed**.
- `GraphBuilder` now lives in `pydantic_graph`.
- Durability is a **capability** (`TemporalDurability()` and friends). The `*Agent` wrappers are deprecated until v3.
- `Dataset(name=...)` is required.
- `Agent(instrument=)` becomes `capabilities=[Instrumentation(...)]`.

---

## 2. Features

### 2.1 Agent delegation via tools (usage sharing)

**What:** A parent's tool `await`s `child.run(...)` and returns the child's output.

**When:** Use it for a specialist with a different model, output type or clean context. The delegate's deps must match the parent's, or be a subset of them. Agents are stateless globals, so don't put them in deps.

```python
from pydantic_ai import Agent, RunContext, UsageLimits

selector = Agent('openai:gpt-6.1-sol', name='joke_selection_agent',
                 instructions='Use `joke_factory` to get jokes, then return the single best one.')
generator = Agent('google:gemini-3.8-flash', name='joke_generation_agent', output_type=list[str])

@selector.tool
async def joke_factory(ctx: RunContext, count: int) -> list[str]:   # must be async def
    r = await generator.run(f'Please generate {count} jokes.', usage=ctx.usage)  # + deps=ctx.deps if needed
    return r.output

result = selector.run_sync('Tell me a joke.',
                           usage_limits=UsageLimits(request_limit=5, total_tokens_limit=500))
print(result.output, result.usage)   # usage covers both agents
```

**Gotchas:**
- **Share usage.** `usage=ctx.usage` rolls the child's usage into the parent's totals and `UsageLimits`, which also has `cost_limit` and `tool_calls_limit`.
- **Async only.** `run_sync()` inside a tool raises `UserError`. Use `async def` (and `asyncio.to_thread()` for blocking work).
- **Cancellation.** A delegate that cancels appears to the parent as a failed tool return. A shared `CancellationToken` cancels the whole tree.
- **Temporal.** Tools get a *copy* of `RunContext`, so the delegate's usage is **lost**. Return it explicitly.
- **Naming.** Always set `name=`. It labels spans, names Temporal activities and sets the online-eval target.
- **Shortcut.** Harness `SubAgents` (`from pydantic_ai_harness import SubAgent, SubAgents`) provides one `delegate_task` tool that forwards deps and limits, and gives each delegate a fresh history.

**Doc:** `docs/multi-agent-applications.md#agent-delegation`, `docs/harness/subagents.md`

### 2.2 Programmatic hand-off (and output-function hand-off)

**What:** Agents run in sequence and your code decides what comes next. Deps don't have to match. Pass `message_history=` to share context.

**When:** Wizard flows, human-in-the-loop steps, routing on structured output, and retry-with-history loops.

```python
from pydantic import BaseModel
from pydantic_ai import Agent, RunUsage

class FlightDetails(BaseModel):
    flight_number: str
class Failed(BaseModel):
    """Unable to find a satisfactory choice."""

flight_agent = Agent[object, FlightDetails | Failed]('openai:gpt-6.1-sol', output_type=FlightDetails | Failed)
seat_agent = Agent('openai:gpt-6.1-sol', instructions="Extract the user's seat preference.")

async def main():
    usage = RunUsage()                                    # shared across the whole app
    r = await flight_agent.run('LHR to JFK on Friday', usage=usage)
    if isinstance(r.output, FlightDetails):               # code decides the next agent
        seat = await seat_agent.run('Window, near the front', usage=usage)
```

**One-way variant:** put an async function in the output types, for example `output_type=[hand_off_to_sql_agent, RouterFailure]`. Inside it, call `await sql_agent.run(query, message_history=ctx.messages[:-1])`. Drop that last message, which holds the output tool call. The router never regains control (`docs/output.md#output-functions`).

**Gotchas:**
- **Annotate union outputs.** Each member becomes its own output tool.
- **Retry with feedback** via `result.all_messages(output_tool_return_content='Please try again.')`.
- **Cross-agent history has caveats.** See `docs/message-history.md#sharing-messages-between-agents`.

**Doc:** `docs/multi-agent-applications.md#programmatic-agent-hand-off`

### 2.3 `pydantic_graph`: BaseNode, End, GraphRunContext, state, deps

**What:** A type-hint-driven async graph library with **no dependency on pydantic-ai**, although it powers the agent loop.
- A node is a `@dataclass` subclass of `BaseNode[StateT, DepsT, RunEndT]`.
- Its `async run(self, ctx: GraphRunContext[StateT, DepsT])` returns the next node or `End(value)`.
- **The return annotation defines the outgoing edges.**

**When:** Explicit typed, diagrammable state machines, such as a write → critique → rewrite loop or an FSM. Plain Python is usually shorter.

**V2:** every graph is assembled with **`GraphBuilder`**, even one made only of BaseNodes. `pydantic_graph.Graph` is now just what `g.build()` returns; there is no old-style `Graph(nodes=[...])` (verified in `pydantic_graph/__init__.py`). A `@g.step` builds the first node from `ctx.inputs`.

```python
from __future__ import annotations
from dataclasses import dataclass, field
from pydantic_graph import BaseNode, End, GraphBuilder, GraphRunContext, StepContext

@dataclass
class Log:
    seen: list[int] = field(default_factory=list)

@dataclass
class Countdown(BaseNode[Log, object, str]):          # state, deps (object = any), End type
    n: int
    async def run(self, ctx: GraphRunContext[Log]) -> Countdown | End[str]:
        ctx.state.seen.append(self.n)
        return End('liftoff') if self.n == 0 else Countdown(self.n - 1)

g = GraphBuilder(state_type=Log, input_type=int, output_type=str)
@g.step
async def start(ctx: StepContext[Log, None, int]) -> Countdown:
    return Countdown(ctx.inputs)
g.add_reachable(Countdown)                             # edges inferred from annotations
g.add(g.edge_from(g.start_node).to(start))
graph = g.build()   # state=Log(); await graph.run(state=state, inputs=3) -> 'liftoff'; print(graph) -> mermaid
```

**Gotchas:**
- **Generics are positional.** A node that ends with an `int` but has no deps is `BaseNode[S, object, int]`.
- **Running.** `graph.run(state=, deps=, inputs=)` is keyword-only and returns the **raw output**. It mutates state in place, and `run_sync()` also exists.
- **Registration.** `add_reachable()` doesn't connect `g.start_node`. Configure step bridges before calling it, or use `g.add(g.node(A), g.node(B))` instead.
- **Cross-module nodes.** Use `from __future__ import annotations` and import the *module*, or you get a circular `ImportError`.
- **Agents inside nodes.** Keep their message history in state (`ctx.state.msgs += result.new_messages()`).

**Doc:** `docs/graph.md`

### 2.4 Graph builder API (steps, decisions, map/broadcast, joins)

**What:** A builder made of plain functions.
- **Steps** have the form `@g.step async def f(ctx: StepContext[State, Deps, In]) -> Out`. `ctx.inputs` holds the previous step's output.
- **Edges** are explicit: `g.add(g.edge_from(a).to(b))`.
- **Fan-out** uses `.map()` for one task per item, or `.to(a, b, c)` to broadcast.
- **Fan-in** uses `g.join(reducer, initial_factory=...)`. Built-in reducers are `reduce_list_append`, `reduce_list_extend`, `reduce_dict_update`, `reduce_sum`, `reduce_null` and `ReduceFirstValue`, or write a custom `(current, inputs) -> new`.
- **Branching** uses `g.decision().branch(g.match(T).to(step))`, and the first match wins.
- **Extras:** edge `.transform()`, and `@g.stream` for generator steps.

| | BaseNode (class) style | Builder (function) style |
|---|---|---|
| Edges | from `run()` return annotations | explicit `edge_from().to()` |
| Data | node dataclass fields | `ctx.inputs` along edges |
| Parallelism | none | `.map()`, broadcast, joins |
| Branching | return a different node | `g.decision()` + `g.match()` |

Both styles mix in one builder.

```python
from pydantic_ai import Agent
from pydantic_graph import GraphBuilder, StepContext, reduce_list_append

summarizer = Agent('openai:gpt-6.1-sol', instructions='Summarize in one sentence.')
g = GraphBuilder(input_type=list[str], output_type=list[str])

@g.step
async def summarize(ctx: StepContext[None, None, str]) -> str:
    return (await summarizer.run(ctx.inputs)).output

collect = g.join(reduce_list_append, initial_factory=list[str])
g.add(g.edge_from(g.start_node).map().to(summarize),    # one parallel task per doc
      g.edge_from(summarize).to(collect),
      g.edge_from(collect).to(g.end_node))
graph = g.build()   # await graph.run(inputs=['doc 1...', 'doc 2...'])
```

**Gotchas:**
- **Completion order.** A join reduces in completion order, not input order. To keep input order, carry `(index, item)` and use `reduce_dict_update`. This matters under durable engines too.
- **Shared state.** Parallel tasks share one mutable state object.
- **Matching complex types.** Unions and `Literal`s in `g.match()` need `TypeExpression[...]`.
- **Empty `.map()` skips the join** unless you pass `add_mapping_edge(..., downstream_join_id=join.id)`.
- **Races.** Use `ReduceFirstValue`, or `ctx.cancel_sibling_tasks()` in a reducer.
- **Stepping through a run.** `async with graph.iter(...) as run: async for event in run:` yields `GraphTask` lists, then an `EndMarker`. Use `run.next(value)` to advance manually.

**Doc:** `docs/graph/builder/{index,steps,decisions,parallel,joins}.md`

### 2.5 Mermaid diagrams and (removed) graph persistence

**Mermaid:** `graph.render(title=..., direction='LR')` or `print(graph)` gives a `stateDiagram-v2`. A union return becomes a `<<choice>>` node. Steps take `label=`, and so do edges via `.label('...')`.

**Persistence was removed in V2** ("complexity of achieving consistent snapshotting with parallel execution"). Replacements:
- **Save, resume or fork an agent run:** Harness `StepPersistence`.
- **Store chats:** `result.conversation` with `ConversationTypeAdapter` or `ConversationStore` (`docs/persistence.md`).
- **Survive crashes:** a durable engine.

For resumable *graphs* you have to serialize state yourself. The docs give no recipe.

**Gotcha:** `docs/comparisons/vs-langchain-langgraph.md` still claims pydantic-graph has "persistence for pausing and resuming". **That claim is stale.**

**Doc:** `docs/graph/builder/index.md#persistence-and-resumability`

### 2.6 Durable execution

**What:** The engine journals each model request and wrapped tool call as a durable unit, then replays completed units and retries the one in flight. In V2 you attach **one durability capability** to a normal `Agent`. **A run is durable only when `agent.run()` executes inside the engine's workflow or flow.**

**When:** Runs that must survive crashes, deploys or outages, or that wait days for a human. **Durability is not storage.** A `jsonb` column of `Conversation` is enough for chats.

| Engine | API | Pick it when… | Caveats |
|---|---|---|---|
| **Temporal** | `TemporalDurability()` + `PydanticAIWorkflow` + `PydanticAIPlugin` | Heavyweight orchestration: worker fleets, signals, long waits | Deterministic async workflow code. Activities may run in other processes, so deps and metadata must be Pydantic-serializable, with a 2 MB payload cap and a limited `RunContext`. `name` and toolset `id` are required and must stay stable. |
| **DBOS** | `DBOSDurability()` + your `@DBOS.workflow()` | In-process, checkpoints to Postgres or SQLite, no server | **Doesn't wrap plain function tools** (add `@DBOS.step` for I/O). Build agents before `DBOS.launch()`. |
| **Prefect** | `PrefectDurability()` + your `@flow` | You already run Prefect (cached tasks, UI, schedules) | Cache-based, so side effects aren't exactly-once. |
| **Restate** | `RestateAgent(agent)` from `restate.ext.pydantic` (a wrapper) | HTTP-handler services, serverless | Wrap tool I/O in `restate_context().run_typed()`. Make steps idempotent. |
| **Airflow** | `AgentOperator(..., durable=True)` or `@task.agent(durable=True)` | The agent is a DAG task | Recovers through task retries and a step cache. **Not compatible with HITL review or streaming.** |
| Harness | `AWSLambdaDurability`, `AbsurdDurability`, `PGTaskDurability`, `AzureDurableTaskDurability` | Lambda, Postgres-only engines, Azure | `docs/harness/*.md` |
| Custom | `pydantic_ai.durable_exec` builder | A new engine | Stable public builder |

```python
from temporalio import workflow
from pydantic_ai import Agent
from pydantic_ai.durable_exec.temporal import PydanticAIWorkflow, TemporalDurability

agent = Agent('openai:gpt-6.1-sol', name='geography',            # name -> stable activity names
              capabilities=[TemporalDurability()])

@workflow.defn
class GeographyWorkflow(PydanticAIWorkflow):
    __pydantic_ai_agents__ = [agent]                              # plugin registers its activities
    @workflow.run
    async def run(self, prompt: str) -> str:
        return (await agent.run(prompt)).output
# client = await Client.connect('localhost:7233', plugins=[PydanticAIPlugin()])
# async with Worker(client, task_queue='geography', workflows=[GeographyWorkflow]): await client.execute_workflow(...)
```

For DBOS, attach `DBOSDurability()` and wrap the run in `@DBOS.workflow()`. The `system_database_url` can be `sqlite:///x.sqlite`.

**Gotchas:**
- **One engine per agent.** A second raises `UserError`.
- **Opting tools out.** `@agent.tool(durable=False)` runs the tool in workflow code, so it must be deterministic. Async tools only.
- **Deploys.** Changing durable units (tool placement, an `args_validator`, adding `OnlineEvaluation`) breaks in-flight replays. Drain or version first.
- **Unbounded retries.** Temporal's default `maximum_attempts=0` is unlimited and stacks with SDK retries, so set `activity_config` and `model_activity_config`.
- **Temporal plus Logfire.** Pass `plugins=[PydanticAIPlugin(), LogfirePlugin()]` for replay-safe spans, and call `logfire.configure()` first.
- **Migrating from `DBOSAgent` or `PrefectAgent`.** You must add `@DBOS.workflow` or `@flow` yourself, or the run is **silently not durable**.

**Doc:** `docs/durable_execution/{overview,temporal,dbos,prefect,restate,airflow,backends}.md`

### 2.7 `pydantic_evals` core: Dataset, Case, experiments, reports

**What:** Code-first evaluation of any stochastic function.
- A `Dataset` holds `Case`s, dataset-wide `evaluators`, and `report_evaluators`.
- Each `Case` has `inputs`, optional `expected_output`, `metadata` and per-case `evaluators`.
- An experiment, `evaluate()` or `evaluate_sync()`, runs a task over the cases and returns an `EvaluationReport`.
- The package doesn't depend on pydantic-ai. Install `pydantic-evals[logfire]` to capture spans.

**When:** Regression gates on prompt, model or tool changes. A/B tests via `report.print(baseline=old_report)`. Measuring variance with `repeat=`.

```python
from pydantic_ai import Agent
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Contains, IsInstance, LLMJudge

agent = Agent('openai:gpt-6.1-sol', name='geo', instructions='Answer in one short sentence.')
dataset = Dataset(
    name='capital_quiz',                                 # required in V2
    cases=[Case(name='france', inputs='What is the capital of France?', expected_output='Paris')],
    evaluators=[IsInstance(type_name='str'), Contains(value='Paris'),
                LLMJudge(rubric='Answer is correct and concise', include_input=True)],
)
async def answer(question: str) -> str:
    return (await agent.run(question)).output

report = dataset.evaluate_sync(answer, max_concurrency=4, repeat=3)
report.print(include_input=True, include_output=True, include_reasons=True)
```

Other keyword-only arguments (from source): `name`, `progress`, `task_name`, `task_timeout`, `retry_task` / `retry_evaluators` (Tenacity configs), `metadata` (experiment-level), and `lifecycle=` (a `CaseLifecycle` **class** with `setup`, `prepare_context` and `teardown`, instantiated once per case).

**Gotchas:**
- **Repeats.** With `repeat>1`, cases are renamed `name [i/N]`. `report.case_groups()` groups them, and averaging happens per group first.
- **Custom data.** `increment_eval_metric()` and `set_eval_attribute()` inside the task appear as `ctx.metrics` and `ctx.attributes`. Pydantic AI adds `requests`, token counts and `cost` automatically.
- **Case evaluators run concurrently** (`task_group_gather`). The docs claim the LLM judge "only runs if basic checks pass", which is **not true per source**.

**Doc:** `docs/evals.md`, `docs/evals/{quick-start,core-concepts}.md`, `docs/evals/how-to/*.md`

### 2.8 Evaluators: built-in, custom, function, LLMJudge, GEval, report-level

**What:**
- **Built-in:** `EqualsExpected`, `Equals(value=)`, `Contains(value=, case_sensitive=)`, `IsInstance(type_name=)`, `MaxDuration(seconds=)`, `LLMJudge`, `GEval` and `HasMatchingSpan`, plus the agentic set in 2.9.
- **Report-level** (`report_evaluators=`): `ConfusionMatrixEvaluator`, `PrecisionRecallEvaluator`, `ROCAUCEvaluator`, `KolmogorovSmirnovEvaluator`, or a custom `ReportEvaluator` that returns `ScalarResult`, `TableResult` and so on.
- **Custom:** a `@dataclass` `Evaluator` with an `evaluate(ctx)` method, sync or async. It returns a bool (assertion), a number (score), a str (label), an `EvaluationReason`, or a dict of these.
- **Function evaluators (new):** a plain `def f(ctx)` works anywhere evaluators are accepted. Wrap it in `FunctionEvaluator(f, evaluation_name=, version=)` to rename or version it.

```python
from dataclasses import dataclass
from pydantic_evals.evaluators import EvaluationReason, Evaluator, EvaluatorContext, GEval, LLMJudge

@dataclass
class WordBudget(Evaluator[str, str]):
    max_words: int = 50                                   # params = dataclass fields
    def evaluate(self, ctx: EvaluatorContext[str, str]) -> dict[str, bool | int]:
        n = len(ctx.output.split())
        return {'within_budget': n <= self.max_words, 'word_count': n}

def mentions_expected(ctx: EvaluatorContext[str, str]) -> EvaluationReason:   # function evaluator
    ok = (ctx.expected_output or '').lower() in ctx.output.lower()
    return EvaluationReason(value=ok, reason=None if ok else f'missing {ctx.expected_output!r}')

judge = LLMJudge(rubric='Polite and on-topic', model='openai:gpt-6-luna', include_input=True,
                 score={'include_reason': True}, assertion={'evaluation_name': 'polite', 'include_reason': True})
coherence = GEval(criteria='coherence', evaluation_steps=['Read it.', 'Check logical flow.', 'Score 1-5.'])
```

**LLMJudge:**
- **Output.** The default is the assertion `LLMJudge_pass` with a reason. `score={...}` adds `LLMJudge_score`, from 0 to 1.
- **Default model.** It is still `'openai:gpt-5.2'` in source. Change it with `llm_as_a_judge.set_default_judge_model()`.
- **Good practice.** Use `temperature=0` and specific rubrics. Put judges on individual cases to build golden datasets.
- **Validate it against human labels.** Run it over stored outputs with an identity task, then compare using a confusion-matrix `ReportEvaluator` (recipe in `llm-judge.md`).

**GEval** returns the raw integer on `score_range` (not normalized), and fails if the score is out of range.

**RAG and translation metrics.** `standard-quality-metrics.md` gives rubric *recipes* (not classes) approximating Ragas metrics and GEMBA. For exact parity, wrap Ragas or DeepEval in an `Evaluator`.

**Gotchas:**
- **`@dataclass` is required.**
- **Function evaluators serialize by name only.** Re-pass them via `custom_evaluator_types` when loading. Lambdas can't be saved.

**Doc:** `docs/evals/evaluators/{overview,built-in,custom,llm-judge,report-evaluators,standard-quality-metrics,framework-integrations}.md`

### 2.9 Span-based and agentic (trajectory) evaluation

**What:** Grade *how* the answer was produced, using the OTel spans captured during the task.

**Building blocks:**
- **`HasMatchingSpan(query=...)`** takes a `SpanQuery`. It can match on name (`name_equals`, `name_contains`, `name_matches_regex`), attributes, status or duration. It combines with `not_`, `and_` and `or_`, and walks the tree with `some_`/`no_` `child_has`, `descendant_has` and `ancestor_has`.
- **Custom evaluators** can use `ctx.span_tree.find()`, `.first()` and `.any()`.
- **Agentic evaluators** are deterministic and make no LLM calls:
  - `ToolCorrectness(expected_tools=, allow_extra=)` checks which tools were called, as a multiset.
  - `TrajectoryMatch(expected_trajectory=, order='exact'|'in_order'|'any_order')` scores call order as an F1.
  - `ArgumentCorrectness(tool_name=, expected_arguments=, match_mode='subset')` checks arguments.
  - `MaxToolCalls` and `MaxModelRequests` enforce budgets.

**When:** RAG (it searched before answering), safety (a tool was never called), checking delegation, and efficiency regressions.

```python
import logfire
from pydantic_evals.evaluators import HasMatchingSpan, MaxToolCalls, ToolCorrectness, TrajectoryMatch

logfire.configure(send_to_logfire='if-token-present')   # captures spans locally; no account needed
logfire.instrument_pydantic_ai()                         # or Agent.instrument_all(): agent/tool spans

evaluators = [
    ToolCorrectness(expected_tools=['search', 'rerank'], allow_extra=True),
    TrajectoryMatch(expected_trajectory=['search', 'rerank'], order='in_order'),
    MaxToolCalls(max_calls=5),
    HasMatchingSpan(query={'name_equals': 'task_execution',                     # "never" check, anchored
                           'no_descendant_has': {'name_contains': 'delete_'}},  # on a root span in the task
                    evaluation_name='never_deleted'),
]
```

**Gotchas:**
- **Span names.** Default spans are named `invoke_agent <agent>` and `execute_tool <tool>` (per `_instrumentation.py`), so prefer `name_contains`.
- **"Never" checks.** `{'not_': X}` passes if *any* span fails `X`. To assert something never happened, root the query on a span and use `no_descendant_has`.
- **What counts as a tool call.** Only local tools count, so native or provider tools are invisible. Failed attempts are excluded except in `MaxToolCalls`. **Sub-agent calls do count.**
- **`include_content=False` breaks `ArgumentCorrectness`.** Instrument with content only in the eval process.

**Doc:** `docs/evals/evaluators/{span-based,agentic}.md`

### 2.10 Dataset serialization and generation

**What:**
- **Save.** `dataset.to_file('cases.yaml')` (or `.json`) also writes `cases_schema.json` plus a `$schema` header, so editors can autocomplete.
- **Load.** `Dataset[In, Out, Meta].from_file(path, custom_evaluator_types=[...])`. `from_text` and `from_dict` also exist.
- **Generate.** `generate_dataset()` has an LLM write typed cases.

```python
from pydantic import BaseModel
from pydantic_evals import Dataset
from pydantic_evals.generation import generate_dataset

class Q(BaseModel, use_attribute_docstrings=True):
    question: str
    """A question to answer"""
class A(BaseModel, use_attribute_docstrings=True):
    answer: str
    """The answer"""

async def main():
    ds = await generate_dataset(dataset_type=Dataset[Q, A, dict], n_examples=5,
                                extra_instructions='World capitals; mix easy and hard.')
    ds.to_file('capitals.yaml')     # + capitals_schema.json
```

**Gotchas:**
- **Default model.** `model='openai:gpt-5.2'` per source.
- **Fragile parsing.** It requests plain-text JSON and parses it with `from_text`, not structured output, so a malformed reply raises `ValidationError`.
- **Naming.** The dataset is called `'generated'` unless you pass `path=`.
- **Review before committing.** It may attach `EqualsExpected` to every case.

**Doc:** `docs/evals/how-to/{dataset-management,dataset-serialization}.md`

### 2.11 Online evaluation

**What:** The same evaluators run in the background on live calls. Attach them to a function with `@evaluate(...)` (`pydantic_evals.online`), or to an agent with the `OnlineEvaluation(evaluators=[...])` capability (`pydantic_evals.online_capability`).
- Results are emitted as OTel `gen_ai.evaluation.result` events, which Logfire shows as Live Evaluations.
- `OnlineEvaluator(evaluator=, sample_rate=, max_concurrency=)` sets per-evaluator options, and `OnlineEvalConfig(default_sink=, default_sample_rate=)` sets defaults.
- Sinks, such as `CallbackSink`, run in addition to the events.
- `wait_for_evaluations()` is for tests.

**When:** Drift monitoring, cheap checks on all traffic with a judge on a sample, and harvesting dataset cases.

```python
from pydantic_ai import Agent
from pydantic_evals.evaluators import EvaluatorContext, LLMJudge
from pydantic_evals.online import OnlineEvaluator
from pydantic_evals.online_capability import OnlineEvaluation

def not_empty(ctx: EvaluatorContext) -> bool:
    return bool(ctx.output)

agent = Agent('openai:gpt-6.1-sol', name='support',          # name = eval "target"
              capabilities=[OnlineEvaluation(evaluators=[
                  not_empty,                                                    # every run
                  OnlineEvaluator(evaluator=LLMJudge(rubric='Polite and on-topic'),
                                  sample_rate=0.05, max_concurrency=2),        # 5% of runs
              ])])
```

**Gotchas:**
- **Timing.** Evaluators dispatch after the run completes (for streams, after the context manager exits). If the worker dies, pending results are lost.
- **Durable engines.** You must pass `OnlineEvaluation(id='...')`, or construction raises `UserError`. Under Temporal there is no `span_tree`, and Prefect flow retries evaluate twice.

**Doc:** `docs/evals/online-evaluation.md`

### 2.12 Logfire / OpenTelemetry

**What:** Pydantic AI emits OTel GenAI-semconv traces: one per run, with spans for each model request and tool call. It also records metrics:
- `gen_ai.client.token.usage`
- `operation.cost`
- `gen_ai.client.operation.time_to_first_chunk`

Logfire is the first-class viewer, but any OTel backend works. Eval experiments also appear in Logfire, along with CI provenance.

```python
import logfire
from pydantic_ai import Agent, InstrumentationSettings
from pydantic_ai.capabilities import Instrumentation

logfire.configure(send_to_logfire='if-token-present')  # no token -> nothing sent to Logfire
logfire.instrument_pydantic_ai()                      # all agents
logfire.instrument_httpx(capture_all=True)            # raw provider HTTP bodies/headers

private = Agent('openai:gpt-6.1-sol', name='private_agent',    # per-agent override (V2 style)
                capabilities=[Instrumentation(settings=InstrumentationSettings(include_content=False))])
# No Logfire: configure an OTel SDK TracerProvider + exporter, then Agent.instrument_all()
# Logfire SDK -> other backend: OTEL_EXPORTER_OTLP_ENDPOINT=... and logfire.configure(send_to_logfire=False)
```

**Gotchas:**
- **Setup.** Use `uvx logfire-cli wizard --task pydantic-ai`. The `.logfire/` directory it writes is gitignored but **not** excluded from Docker build contexts.
- **`InstrumentationSettings`:** `include_content=False`, `include_binary_content=False`, `include_model_request_parameters=False`, `tracer_provider=`, and `version=` (default 5; 6 is opt-in and uses the `role: "tool"` message role).
- **Usage attributes.** Run spans use `gen_ai.aggregated_usage.*` so usage isn't double counted.
- **Built-in prompt-cache health:** `pydantic_ai.cache.hit_ratio`, `.collapsed` and `.collapse_reason`.

**Doc:** `docs/logfire.md`, `docs/evals/how-to/logfire-integration.md`

### 2.13 Comparisons and migration

**What:** `docs/comparisons/` has 14 pages, each with Framework and Features tables and a FAQ (last checked September 2026): LangChain/LangGraph, CrewAI, the OpenAI and Claude Agent SDKs, Google ADK, Microsoft Agent Framework, Strands, OpenHands, Vercel AI SDK, Mastra, Agno, LiveKit, Pipecat and Pi.

`docs/framework-migration.md` lists **coding-agent migration skills**, installed with `uvx library-skills --all`, for example `migrating-langchain-to-pydantic-ai`. They cover LangChain, Agno, the Claude Agent SDK, ADK, Mastra, the OpenAI Agents SDK, Pi, and Vercel/Eve. **There is no skill for CrewAI, Microsoft, Strands or OpenHands.**

**Mapping:**
- Crews map to sub-agents or delegation.
- LangGraph or CrewAI `Flow` map to `pydantic-graph`, but only for real state machines.
- OpenAI `handoff`s map to programmatic or output-function hand-off.

The pages also argue: provider-agnostic, OTel and Logfire rather than LangSmith, nine durable integrations, and enterprise support without a platform.

**Migration philosophy:** preserve behavior, not API names. Trace a real request, port the smallest complete path, test old against new at the same boundary, and remove the old framework last.

**Gotcha:** the tables are vendor-written. The LangGraph page's persistence claim is stale.

**Doc:** `docs/comparisons/*.md`, `docs/framework-migration.md`, `docs/migration.md`

---

## 3. Experiment ideas (increasing difficulty)

1. **Offline delegation.** Build the selector/generator pair on `TestModel()`. Compare `result.usage` with and without `usage=ctx.usage`, make `UsageLimits(request_limit=2)` trip, then call `run_sync` in the tool to see the `UserError`.
2. **Router showdown.** Compare an output-function hand-off (`output_type=[to_math_agent, to_poetry_agent, RouterFailure]`) with code branching on a `Literal` classifier. Compare the two traces in Logfire or `otel-tui`.
3. **BaseNode FSM.** Port the vending machine to stateful `BaseNode`s with `add_reachable`. `print(graph)` for Mermaid, and drive it with `graph.iter()`, logging each `GraphTask`.
4. **Parallel builder graph.** Map an agent over documents with `reduce_list_append` and watch the order change. Fix it with index plus `reduce_dict_update`. Add a `g.decision()` and race two models with `ReduceFirstValue`.
5. **First eval suite.** Write 10 YAML cases with schema autocomplete, using `Contains`, `WordBudget`, a function evaluator and per-case judges. Run with `repeat=3`, change the prompt, and compare with `report.print(baseline=old)`.
6. **Judge calibration.** Hand-label about 20 outputs. Run an identity task with `LLMJudge` and a confusion-matrix `ReportEvaluator`, tune the rubric until agreement is good, then try `GEval`.
7. **Trajectory evals.** Instrument a RAG agent with `search` and `rerank` tools and assert `ToolCorrectness`, `TrajectoryMatch`, `ArgumentCorrectness` and `MaxModelRequests`. Add a sub-agent and see its calls counted.
8. **Online evals locally.** Attach `OnlineEvaluation` (function evaluator at 100%, judge at 10%) with a `CallbackSink`. Assert in pytest after `wait_for_evaluations()`, then view the events in Logfire.
9. **DBOS on SQLite.** Use `DBOSDurability()` with a slow `@DBOS.step` tool. Kill the process mid-run, restart, and check the model step isn't re-billed. Then drop `@DBOS.workflow` to see the silent non-durable trap.
10. **Temporal end to end.** Run `temporal server start-dev` with `TemporalDurability`, `FunctionToolset(id=...)`, `PydanticAIPlugin` and `LogfirePlugin`. Run a parallel graph in a workflow, kill the worker, and verify replay without duplicate spans or lost delegate usage.

---

## 4. Key takeaways

- **Climb the ladder only as far as you need.** Go from a single agent, to delegation (`usage=ctx.usage`, async tools), to hand-off. Use graphs only for real state machines or parallel dataflow.
- **pydantic-graph V2 builds everything with `GraphBuilder`.** It mixes `BaseNode`s (edges from annotations) and `@g.step` functions (explicit map/join/decision edges). `run()` returns the raw output, and `print(graph)` gives Mermaid.
- **Graph persistence is gone.** Use `StepPersistence` for agent checkpoints, `Conversation` for chats, and a durable engine for crashes.
- **Durability is one capability per agent.** It only takes effect inside the engine's workflow. Temporal is the most powerful and the strictest. DBOS is the simplest. Prefect and Airflow suit existing pipelines.
- **Evals are unit tests for stochastic code.** You get a `Dataset` of `Case`s, class or function evaluators, `repeat=`, baselines and report analyses.
- **Grade trajectories, not just answers.** Span and agentic evaluators read production's OTel spans. Match names like `invoke_agent X` and `execute_tool Y`.
- **Close the loop.** `OnlineEvaluation` samples evaluators on live runs and emits OTel events. Under durable execution it needs an `id`.
- **Everything is OTel.** `logfire.instrument_pydantic_ai()` or `Agent.instrument_all()`, plus `InstrumentationSettings` for privacy.

---

### Appendix: doc inconsistencies found
- **Graph persistence.** `comparisons/vs-langchain-langgraph.md` claims graph persistence, which V2 removed.
- **Evaluator ordering.** `evals/evaluators/built-in.md` says the judge "only runs if basic checks pass". In fact all evaluators run concurrently.
- **Span names.** `evals/evaluators/span-based.md` uses `name_equals: 'master_agent'`, but the actual span is `invoke_agent master_agent`.
- **Default models.** `pydantic_evals` hard-codes `'openai:gpt-5.2'` as the judge and generator default. Pass `model=`.
