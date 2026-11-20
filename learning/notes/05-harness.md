# 05 — Pydantic AI Harness (`docs/harness/`)

Clone: `/home/ubuntu/pydantic-dev/pydantic-ai-experiments` (main, Pydantic AI 2.71 → Harness 0.71). Doc paths are relative to `docs/harness/`. Source: `src/pydantic_ai_harness/pydantic_ai_harness/<capability>/` (each has a `README.md` twin). Sidebar: `docs/navigation.yml` mixes harness pages with core `docs/capabilities/*` under one "Capabilities" section.

> Docs write models as `{{ anthropic:large }}` aliases (`docs/model_aliases/aliases.json`: anthropic small/medium/large = `claude-haiku-5-5`/`claude-sonnet-5-5`/`claude-opus-5-5`; openai:medium = `gpt-6.1-sol`). Examples below use resolved strings. For free offline runs use `pydantic_ai.models.test.TestModel()`.

## 1. Overview

**Pydantic AI Harness** (`pip install pydantic-ai-harness`, import `pydantic_ai_harness`) is the official *capability library* for Pydantic AI: 100+ self-contained units of behaviour you put in `Agent(capabilities=[...])` (`index.md`). "Harness" means everything around the model (loop, tools, context management); core already has a lean one, and this package adds what long-running, file-touching, unattended agents need: workspaces/sandboxes, file & shell tools, memory, planning, sub-agents, compaction, guardrails, budgets, durable engines, SaaS integrations. There is one primitive — the **capability** (tools + hooks + instructions + model settings); even the packaged agents `Coder` and `Researcher` are combined capabilities you can take apart. It is a separate package in the same monorepo (`src/pydantic_ai_harness/`), versioned `0.X.Y` in lockstep with `pydantic-ai 2.X.Y` and pinning that exact `pydantic-ai-slim`; 0.x means APIs may change between minors (with deprecation warnings). Extras pass providers through (`pydantic-ai-harness[coder,anthropic]`) and most capabilities have their own extra (`[modal]`, `[codemode]`, `[skills]`, `[github]`...). The core/harness split is mechanical: core keeps what needs model/framework support (Thinking, WebSearch, MCP, native Compaction, ToolSearch, Caching, `LocalWorkspace`). A third package, **CLAI** (`pydantic-ai-pax`, command `pax`; its page `clai2.md` is unpublished), is a terminal coding agent built on `Coder` — not core's `clai` chat CLI.

**Plugging in.** File/command capabilities need a **workspace** (core concept, `docs/workspace.md`): `LocalWorkspace('.')` from `pydantic_ai.capabilities` (*not* a sandbox) or a sandbox capability (`ModalSandbox()`, `DockerContainer(...)`). Without one, `Coder`/`FileSystem`/`Shell`/`RepoContext`/`Skills`/`FileMemoryStore` fail at run start. Your own tools use `ctx.workspace.run([...])`. **List order matters** (compaction before `Memory`; `HandleDeferredToolCalls` after `Permissions`).

```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import LocalWorkspace, WebSearch
from pydantic_ai_harness import Coder, Memory
from pydantic_ai_harness.memory import FileMemoryStore

agent = Agent('openai:gpt-6.1-sol', capabilities=[
    LocalWorkspace('.'), Coder(), WebSearch(), Memory(FileMemoryStore('.agent-memory'))])
```
Zero-code: `uvx --with "pydantic-ai-harness[coder]" clai -a pydantic_ai_harness.coder:coder_agent -m <model>`. Repo examples: `src/pydantic_ai_harness/examples/{coding_agent,research_agent,pixeltable_video}.py` (`examples.md`).

## 2. Catalogue by theme (What / Use when)

Imports are `from pydantic_ai_harness import X` unless a submodule is given.

### 2.1 Packaged harnesses
| Capability | What | Use when | Doc |
|---|---|---|---|
| `Coder` `[coder]` | FileSystem + persistent `shell` + RepoContext + `delegate_task` to itself + context controls | Coding agent in one line | `coder.md` |
| `Researcher` `[researcher]` | Search + fetch + sub-researcher + bounded output, cited answers | Web research agent | `researcher.md` |

### 2.2 Workspaces, sandboxes, code execution
Shared sandbox lifecycle (§3.2): created on first use, **outlives the run** (cloud ones keep billing), continues via `message_history`, reattach with `result.workspace.ref` → `run(..., workspace=ref)`, cleanup via `<Cap>().destroy(ref)`.

| Capability | What | Use when | Doc |
|---|---|---|---|
| `ModalSandbox` `[modal]` | Modal cloud sandbox (≤24h) | Isolated cloud exec | `modal-sandbox.md` |
| `E2BSandbox` `[e2b]` | E2B sandbox, dev-server previews | Cloud + preview URLs | `e2b-sandbox.md` |
| `KubernetesSandbox` `[kubernetes]` | Pod from agent-sandbox warm pool | Own cluster | `kubernetes-sandbox.md` |
| `RenderSandbox`, `SpritesSandbox`, `DaytonaSandbox`, `BoxdSandbox` | Render / persistent Fly Sprite / Daytona / boxd (forkable) machines | That provider | `render-sandbox.md`, `sprites-sandbox.md`, `daytona-sandbox.md`, `boxd-sandbox.md` |
| `SmolSandbox` `[smol]`, `BoxLiteSandbox` `[boxlite]` | Local microVMs, no cloud (BoxLite: egress allow-list) | Local VM isolation | `smol-sandbox.md`, `boxlite-sandbox.md` |
| `OpenSandbox` `[opensandbox]` | Your own OpenSandbox server (Docker/k8s) | Self-hosted | `opensandbox-sandbox.md` |
| `DockerContainer` (no extra) | Local Docker/Podman container | Cheapest local isolation (shares kernel) | `docker-container.md` |
| `SSHWorkspace` | Remote host via your `ssh`; no isolation | Build box | `ssh-workspace.md` |
| `BubblewrappedWorkspace` | Wraps another workspace in bubblewrap; "not a security boundary" | Extra guardrail on SSH/local | `bubblewrap-sandbox.md` |
| `CodeMode` `[codemode]` | Tools become one `run_code`; model writes Python run in Monty sandbox | Many dependent tool calls → one turn | `code-mode.md` |
| `IPythonCodeMode` `[ipython]` | `run_code` on a persistent IPython kernel, full CPython | Trusted local data work only | `ipython-code-mode.md` |

### 2.3 Filesystem, shell, coding helpers
| Capability | What | Use when | Doc |
|---|---|---|---|
| `FileSystem` | 8 file tools + opt-in ripgrep `list_files`/`grep`; root containment, allow/deny/read-only globs | Any file-touching agent | `filesystem.md` |
| `Shell` | `run_command`, background `start/check/stop_command`, opt-in persistent `shell`; allow/deny lists, env scrubbing | Running commands | `shell.md` |
| `SmartSearch` | Plain-English code search ranked by a judge model (`system-one:...`, `typesafe:jev-latest`) | Large codebases | `smart-search.md` |
| `RepoContext` | Loads `AGENTS.md`/`CLAUDE.md` root→cwd and nested on traversal; optional asset inventory | Repo-aware runs | `repo-context.md` |
| `ReportStaleFiles` | Warns when a file read/written has since changed | Concurrent editors | `report-stale-files.md` |
| `RequireVerification` | Sends agent back to run tests/lint if it finishes after edits without a passing check | Proven "done" | `require-verification.md` |
| `RepairToolArguments` | `json-repair` on malformed tool-arg JSON | Weak/local models | `repair-tool-arguments.md` |
| `Macroscope` | Local Macroscope code review → findings | Self-review loops | `macroscope.md` |
| `LocalStack` | Emulated AWS + AWS CLI tools | Infra agents w/o AWS | `localstack.md` |

### 2.4 Context management
| Capability | What | Use when | Doc |
|---|---|---|---|
| Compaction: `TieredCompaction`, `ClearToolResults`, `SlidingWindowCompaction`, `SummarizingCompaction`, `DeduplicateFileReads`, `RelevanceCompaction`, `ClampOversizedMessages`, `FallbackCompaction`, `CompactOnRequest`, `PruneToolResults`, `WarnNearLimits`, `ReportContextUsage` | Model-agnostic history shrinking on `max_messages`/`max_tokens`/`max_fraction` triggers | Long runs on any provider (core `capabilities/compaction.md` = provider-native) | `compaction.md` |
| `ToolOutputLimits` | Size bands → `Truncate`/`Spill` (lossless, adds `read_tool_result`/`grep_tool_result`)/`Summarize`; default spills ≥10k chars | One result floods context | `tool-output-limits.md` |
| `ToolBridge` | Fixed `tool_search`/`tool_describe`/`tool_call` dispatchers | Many/dynamic tools, stable cache | `tool-bridge.md` |
| `WarnOnCacheBusts` | `CacheBustWarning` when cached prefix collapses | Debug cache cost (with core `Caching()`) | `warn-on-cache-busts.md` |
| `LabelCrossModelHistory` | Notes that earlier turns came from another model | Model switch/handoff | `label-cross-model-history.md` |
| `SystemReminders` (`Reminder`, `GoalReanchor`, `LLMReminder`) | Cache-safe mid-run reminders by cadence/condition | Instruction fade | `system-reminders.md` |
| `CurrentTime` | Date/hour in a tz without busting cache | Time-aware agents | `current-time.md` |

### 2.5 Memory, knowledge, persistence
| Capability | What | Use when | Doc |
|---|---|---|---|
| `Memory` | Markdown notebook, 4 tools, bounded injection, namespaces; in-memory/file/SQLite/Postgres/Pixeltable stores | Cross-session memory | `memory.md` |
| `ConversationSearch` | BM25 over StepPersistence snapshots incl. compacted turns | Recall after compaction | `conversation-search.md` |
| `StepPersistence` | Snapshots, event trail, tool-effect ledger; `continue_run`/`fork_run` | Manual crash recovery/branching | `step-persistence.md` |
| `Skills` `[skills]` | `SKILL.md` files as on-demand capabilities (`load_capability`) | Reusable procedures | `skills.md` |
| `Pixeltable` | Read-only tools over Pixeltable tables/indexes + memory store | Multimodal RAG | `pixeltable.md` |
| `PydanticAIDocs` | On-demand Pydantic AI docs lookup | Agents that build agents | `pydantic-ai-docs.md` |
| Media stores (`.media`) | Content-addressed blob stores (disk/SQLite/S3/Mongo/Postgres) | Small snapshots of multimodal history | `media.md` |

### 2.6 Safety & guardrails
| Capability | What | Use when | Doc |
|---|---|---|---|
| `InputGuardrail`/`OutputGuardrail`/`ToolGuardrail`/`StreamGuardrail` | Guard returns allow/block/replace/retry/approve; detectors for secrets/PII/keywords | Deterministic policy, redaction | `guardrails.md` |
| `Permissions` | Modes full/auto/read-only + allow/ask/deny `PermissionRule`s on tools, args, shell commands | Human-in-the-loop coding | `permissions.md` |
| `ToolCallJudge` (`.tool_call_judge`) | 2nd model answers a risk question per call; "yes" blocks | Automated blocking | `tool-call-judge.md` |
| `ApprovalReviewer` (`.approval_reviewer`) | 2nd model auto-approves low-risk approval-required calls | Approval fatigue | `approval-reviewer.md` |
| `PromptInjectionDefender` | StackOne Defender scans tool results; `block_high_risk=True` withholds | Email/web/ticket readers | `prompt-injection-defender.md` |
| `ArtifactScanner` | Scans memory writes & skills for injection/exfiltration | Persisted artifacts | `artifact-scanning.md` |
| `AskUser` / `DenyUnanswered` | Model asks multiple-choice questions / unanswered asks get denied so unattended runs finish | Clarification / CI runs | `ask-user.md`, `deny-unanswered.md` |
| `Goal` | Async `verify(ctx, output)`; returned string sends the model back | Hard completion check | `goal.md` |
| `TrajectoryJudge` / `RefineOutput` | 2nd model steers every N requests / extra revise rounds | Drift / quality | `trajectory-judge.md`, `refine-output.md` |

### 2.7 Budgets, limits, loop control
| Capability | What | Use when | Doc |
|---|---|---|---|
| `SpendLimits` (+`.spend_limits.Budget`) | USD/token budgets per run/conversation/day/month/total, per-tenant; in-process/Redis/Postgres | Production cost ceilings | `spend.md` |
| `ToolBudgets` | `per_tool`, `total`, `refuse_repeats` → soft tool result | Expensive tools | `tool-budgets.md` |
| `ReportRemainingBudget` | Tells model remaining requests/tools/tokens/$ each request | Graceful wrap-up | `report-remaining-budget.md` |
| `WrapUpAtLimits` | Last allowed request forced to a final answer instead of `UsageLimitExceeded` | Return partial work | `wrap-up-at-limits.md` |
| `DetectLoops` | Repeated calls/results, A-B alternation, repeated text → nudge/error/handler | Stuck agents | `detect-loops.md` |
| `ReportToolErrors` | Tool exceptions become failed tool results | Flaky tools | `report-tool-errors.md` |

### 2.8 Planning, delegation, reasoning
| Capability | What | Use when | Doc |
|---|---|---|---|
| `Planning` | Model-owned todo list, optional subtasks/deps, SQLite/Postgres/Redis stores | Multi-step tasks, planner/executor split | `planning.md` |
| `SubAgents` + `SubAgent` | `delegate_task(agent_name, task)` with per-delegate budgets, disk-defined agents, background `TaskControl` | Specialist delegation | `subagents.md` |
| `DynamicWorkflow` `[dynamic-workflow]` | Orchestrator writes one sandboxed script calling sub-agents (fan-out/chain/vote), `max_agent_calls` | Orchestration is the work | `dynamic-workflow.md` |
| `Peers` | `list_peers`/`send_message` between independent sessions | Peer collaboration | `peers.md` |
| `Advisor` | Consult a stronger model; native on Anthropic/OpenRouter, local fallback | Cheap executor + expert | `advisor.md` |
| `BackgroundTools` | Tools with `metadata={'background': True}` run concurrently; results arrive later | Slow tools | `background-tools.md` |
| `ModelRouter` (`.model_router`) | Router model picks from a named model menu | Cost-aware routing | `model-router.md` |

### 2.9 Web & research (core also has `WebSearch`/`WebFetch`/`XSearch`)
| Capability | What | Use when | Doc |
|---|---|---|---|
| `ExaSearch`, `ExaAgent` `[exa]` | Excerpt search, page reads, cited `deep_search`; Exa Agent runs | Cited research | `exa-search.md` |
| `YouSearch`, `YouResearch` `[youdotcom]` | You.com search, cited answers, deep/finance research | Alt. provider | `youdotcom.md` |
| `KeenableSearch` | Keyless search + page reads, no extra | Zero-setup experiments | `keenable-search.md` |
| `BrowserUse` `[browser-use]` | Delegates to an autonomous browser-use agent | Open-ended web tasks | `browser-use.md` |
| `PlaywrightBrowser` (`.playwright`) | Model drives Chromium (click/type/JS/screenshot) | Dynamic/logged-in pages | `playwright.md` |

### 2.10 SaaS integrations (hosted MCP servers; `integrations.md`)
`GitHub` (`.github`), `Linear` (`.linear`), `GoogleWorkspace(services=[...])` (`.google_workspace`), `Notion` (`.notion`), `Slack` (`.slack`), `LogfireMCP` (`.logfire_mcp`), plus top-level `DayAI`, `Grain`, `Pylon`, `StackOne`, `PostHog`, `Ordinal` (docs: `<name>.md`). Shared pattern: `auth=` token or `(ctx) -> token` for per-user credentials (else env var, e.g. `GITHUB_TOKEN`); approval via toolset wrappers, e.g. `toolsets=[GitHub().get_toolset().approval_required()]` + `output_type=[str, DeferredToolRequests]`; several take `read_only=`. Unlisted MCP service → core `MCP` capability.

### 2.11 Durable execution & production runtime
| Capability | What | Use when | Doc |
|---|---|---|---|
| `AWSLambdaDurability` + `durable_agent_handler` (`.aws_lambda`) | Checkpoints into Lambda durable-function steps | AWS serverless | `aws-lambda.md` |
| `AbsurdDurability` / `PGTaskDurability` (`.pgtask`) | Steps on Postgres-based engines | Postgres-only durability | `absurd.md`, `pgtask.md` |
| `AzureDurableTaskDurability` + `run_durable` | Activities in Durable Task Scheduler | Azure | `azure-durable-task.md` |
| `RenderWorkflows` `[render]` | Chained Render task runs w/ own retries/compute | Background agents on Render | `render-workflows.md` |
| `ManagedPrompt` `[logfire]` | Instructions from a versioned Logfire-managed prompt | Prompt rollout w/o deploy | `managed-prompt.md` |
| core Temporal/DBOS/Prefect/... | `Coder`/`Shell`/`FileSystem` work under them | — | `../workspace.md#durable-execution` |

### 2.12 Interfaces & self-extension
| Item | What | Use when | Doc |
|---|---|---|---|
| ACP *(experimental)* `pydantic_ai_harness.experimental.acp.run_acp_stdio_sync(agent)` | Serve an Agent to Zed etc. over Agent Client Protocol | Agent inside an editor | `acp.md` |
| GitHub Agentic Workflows | Run your Agent headless in Actions with MCP "safe outputs" | Triage bots, PR automation | `gh-aw.md` |
| `CapabilityCreation` | Agent writes/validates capability classes; host loads them next run | Self-extending agents | `capability-creation.md` |
| Unpublished: `clai2.md` (pax client), `mutation-testing.md` (contributor-only) | — | — | — |

## 3. Key entries: minimal examples & gotchas

### 3.1 `Coder` — `coder.md`
```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import LocalWorkspace
from pydantic_ai.workspaces import ReadOnlyWorkspace
from pydantic_ai_harness.coder import Coder

coder = Agent('anthropic:claude-opus-5-5', capabilities=[LocalWorkspace('.'), Coder()])
result = coder.run_sync('Find out why tests/test_parser.py fails and fix the bug it caught.')
result = coder.run_sync('Document the fix in the README.', message_history=result.all_messages())

reviewer = Agent('anthropic:claude-opus-5-5', capabilities=[Coder(instructions='Review the code for bugs.')])
review = reviewer.run_sync('Review the last change.', workspace=ReadOnlyWorkspace(result.workspace))
```
**Gotchas**
- Needs `[coder]` extra (json-repair + ripgrep) or import fails. `LocalWorkspace` isn't a sandbox; `shell` is unrestricted, ignores FileSystem path rules, and commands **outlive the run**.
- Commands get only `PATH`, `HOME`, `LANG`, `LC_*`; pass `LocalWorkspace('.', env={...})`, never `os.environ` (leaks API keys).
- Composition: `FileSystem(content_hashes=False, max_read_chars=50000, tools=[read_file, write_file, edit_file, list_files, grep], max_retries=5)`, `Shell(denied_commands=[], allow_interactive=True, default_timeout=270, tools=['shell'])`, `RepoContext(walk_up='repo_root')`, `SubAgents(include_self=True)`, `ClearToolResults(max_fraction=0.7)`, 64k output truncation, `RepairToolArguments`, caching on, strict schemas off. No `Planning`.
- Bind on `Agent(...)`, not `run(capabilities=...)` (`UserError` unless `sub_agents=False`) — delegates inherit only agent-bound pieces. `autonomy='low'|'medium'|'high'|'max'` is prompt guidance, not enforcement (use `Permissions`).
- Remote sandbox: RepoContext creates it at run start; `Coder(repo_context=False)` for lazy creation.

### 3.2 Sandboxes (`DockerContainer`, `ModalSandbox`, ...) — `docker-container.md`, `modal-sandbox.md`
```python
from pydantic_ai import Agent
from pydantic_ai.workspaces import WorkspaceRef
from pydantic_ai_harness.coder import Coder
from pydantic_ai_harness.docker_container import DockerContainer

agent = Agent('anthropic:claude-opus-5-5', capabilities=[
    DockerContainer(image='python:3.13-slim', allow_internet_access=False), Coder()])
result = agent.run_sync('Write a script that prints the first 10 primes, and run it.')
ref = result.workspace.ref                       # persist it
later = agent.run_sync('Now make it print the first 100.', workspace=ref)

async def cleanup(ref: WorkspaceRef) -> None:
    await DockerContainer().destroy(ref)         # runs never remove it
```
**Gotchas**
- Nothing terminates sandboxes for you (Modal ≤24h unless `sandbox_timeout=`/`idle_timeout=`; Docker: never). Failed runs give no ref → clean up in a `Hooks` `on.run_error` hook (`modal-sandbox.md`).
- Swapping providers is one line; custom tools call `await ctx.workspace.run([...], timeout=...)`.
- Default images lack your deps (Modal: no `pytest`); install `rg`/`git` in the image (the `[coder]` extra installs `rg` on the host only).
- Expired sandbox in history → `WorkspaceUnavailableError`; `workspace='new'` forces fresh. Docker shares the kernel and its default network reaches your LAN.

### 3.3 `FileSystem` + `Shell` + `Permissions` — `filesystem.md`, `shell.md`, `permissions.md`
```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import HandleDeferredToolCalls, LocalWorkspace
from pydantic_ai_harness.file_system import FileSystem
from pydantic_ai_harness.permissions import PermissionDecision, PermissionRequest, PermissionRule, Permissions, ask_permissions
from pydantic_ai_harness.shell import Shell

async def approve(req: PermissionRequest) -> PermissionDecision:
    answer = input(f'{req.reason}\n  {req.subject}\nRun it? [y/N/always] ')
    return PermissionDecision(approved=answer in ('y', 'always'), remember=answer == 'always')

agent = Agent('anthropic:claude-sonnet-5-5', capabilities=[
    LocalWorkspace('./workspace'), FileSystem(), Shell(),
    Permissions('auto', rules=[PermissionRule('deny', command='rm -rf', reason='Delete files one at a time.')]),
    HandleDeferredToolCalls(handler=lambda ctx, requests: ask_permissions(requests, approve)),
])
```
**Gotchas**
- FileSystem containment is "a guardrail, not isolation"; `Shell` ignores `root_dir`. `cwd=` args are deprecated/ignored — set the directory on the workspace.
- `Shell` default denylist (`rm`, `dd`, `mkfs`, `shutdown`...); `allowed_commands` vs `denied_commands` mutually exclusive; only the first token is checked, so `python`/`git`/`make` can do anything. Denials are `ModelRetry`. Output keeps the **tail**. Background jobs log in `.pydantic-ai-harness/shell/` and outlive runs.
- `Permissions` default mode `'full'` asks nothing; `'auto'` asks only `ask_commands` (rm -rf, git push, sudo, curl, installs...); `'read-only'` asks all writes/commands. deny > ask > allow regardless of order. No handler → run ends with `DeferredToolRequests`.
- Delegates don't see run-passed permissions: use `SubAgents(shared_capabilities=[permissions, handler])`.

### 3.4 Compaction — `compaction.md`
```python
from pydantic_ai import Agent
from pydantic_ai_harness import ClearToolResults, ReportContextUsage, SummarizingCompaction, TieredCompaction
from pydantic_ai_harness.compaction import ContextUsageMeasuredEvent

agent = Agent('anthropic:claude-sonnet-5-5', capabilities=[
    TieredCompaction(tiers=[ClearToolResults(keep_pairs=3), SummarizingCompaction(keep_messages=20)],
                     target_tokens=120_000),
    ReportContextUsage(),   # after compaction → measures the compacted history
])

@agent.on_event(ContextUsageMeasuredEvent)
async def show(ctx, event):
    print(f'context {event.fraction:.0%} (resolved={event.resolved})')
```
**Gotchas**
- Prefer `max_fraction=0.9` to absolute `max_tokens` (mutually exclusive); resolved per request from the model's context window. Unknown window → `fallback_context_window` (200K): **`TestModel` never resolves**, so compaction seems to never fire in tests unless you pass `context_window=`.
- The `genai-prices` registry can be wrong (docs: `claude-sonnet-4-5` recorded 1M, real 200K) — pass `context_window=`.
- Standalone `ClearToolResults`/`SlidingWindowCompaction`/`SummarizingCompaction` without a trigger raise `UserError`; tiers inside `TieredCompaction` need none. Any `async def compact(messages, ctx)` object can be a tier.
- Rewrites bust the prompt cache (`min_clear_tokens` limits churn). `pin(...)` from `pydantic_ai_harness.compaction` protects durable state.

### 3.5 `Memory` — `memory.md`
```python
from dataclasses import dataclass
from pydantic_ai import Agent
from pydantic_ai_harness import Memory
from pydantic_ai_harness.memory import SqliteMemoryStore

@dataclass
class Deps:
    user_id: str

agent = Agent('anthropic:claude-sonnet-5-5', deps_type=Deps, capabilities=[
    Memory(SqliteMemoryStore(database='.agent-memory.db'), namespace=lambda ctx: ctx.deps.user_id)])
agent.run_sync('Remember: I prefer pytest over unittest.', deps=Deps('alice'))
print(agent.run_sync('Which test framework do I like?', deps=Deps('alice')).output)
```
**Gotchas**
- Tools: `write_memory` (append / replace unique fragment, compare-and-swap), `read_memory` (steps aside for `FileSystem.read_file` when it can see the files), `delete_memory` (`MEMORY.md` protected), `search_memory`.
- Injection: bounded `<memory>` block (`max_tokens=2000`) on the **first request of a run, only if memory changed** — cache-friendly; mid-run writes reach the model next prompt. `inject_memory=False` = tools only.
- Only `FileMemoryStore` needs a workspace; with `FileSystem` on the same workspace the model can read every namespace, so give the store its own `workspace=LocalWorkspaceBackend(...)` for multi-user. One writer per directory. Namespaces aren't authorization.
- List compaction before `Memory`; `scanner=ArtifactScanner()` refuses injected writes.

### 3.6 `StepPersistence` — `step-persistence.md`
```python
from pydantic_ai import Agent
from pydantic_ai_harness import StepPersistence
from pydantic_ai_harness.step_persistence import SqliteStepStore, continue_run

store = SqliteStepStore(database='runs.db')
agent = Agent('openai:gpt-6.1-sol', capabilities=[StepPersistence(store=store)])

async def recover(run_id: str):
    for rec in await store.list_unresolved_tool_effects(run_id=run_id):
        print(f'{rec.tool_name} ({rec.tool_call_id}) may or may not have run')
    history = await continue_run(store, run_id=run_id)   # fork_run(...) to branch instead
    return await agent.run('continue investigating', message_history=history)
```
**Gotchas**
- Not a durable engine: nothing auto-retries; you decide `continue_run` vs `fork_run`. In-flight tools are `started` effects; annotate side effects with `annotate_tool_effect(store, ctx, idempotency_key=..., effect_summary=...)`.
- `continue_run` skips `interrupted` snapshots unless `include_interrupted=True`; raises `LookupError` if none.
- IDs: `conversation_id` groups runs (`store.list_runs(conversation_id=...)`); with `agent_name=` the stored run_id is derived from `(agent_name, ctx.run_id)`; reusing an explicit `run_id` raises `ValueError`.
- Backends: InMemory, File, SQLite, Mongo (`[mongodb]`), Postgres (your asyncpg pool).

### 3.7 `SubAgents` — `subagents.md`
```python
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness import SubAgent, SubAgents

researcher = Agent('anthropic:claude-sonnet-5-5', name='researcher', description='Researches a topic and reports findings')
writer = Agent('anthropic:claude-sonnet-5-5', name='writer', description='Turns notes into polished prose')

orchestrator = Agent('anthropic:claude-opus-5-5', capabilities=[SubAgents(agents=[
    SubAgent(researcher, usage_limits=UsageLimits(request_limit=20), timeout_seconds=300, max_calls=2),
    SubAgent(writer),
])])
print(orchestrator.run_sync('Research the history of TLS and write a one-paragraph summary.').output)
```
**Gotchas**
- Delegates need a `name`; children get **no parent history** (tasks must be self-contained); parent gets `str(result.output)`.
- Budget/timeout exhaustion returns a soft steering message, not `UsageLimitExceeded`; `forward_usage=True` rolls child usage up.
- `include_self=True` adds `self`; `max_depth=3`. `agent_folders='agents'` loads Claude-style `.md` / Codex `.toml` agents from the workspace (`.agents/`, `.claude/`, `.codex/`); frontmatter `model` ignored; unsupported on Temporal.
- `task_control=TaskControl(...)` (`pydantic_ai_harness.sub_agents`) adds background tasks: `list_tasks`, `check_task`, `message_task`, `answer_task`, `cancel_task`.

### 3.8 `Planning` — `planning.md`
```python
from pydantic_ai import Agent
from pydantic_ai_harness import Planning
from pydantic_ai_harness.planning import SqlitePlanStore

store = SqlitePlanStore('plan.db', session='issue-403')
planner = Agent('anthropic:claude-opus-5-5', capabilities=[Planning(store=store)])
executor = Agent('anthropic:claude-sonnet-5-5', capabilities=[Planning(store=store)])

planner.run_sync('Plan the migration of the auth module to OAuth2. Do not execute yet.')
print(executor.run_sync('Execute the plan step by step.').output)
```
**Gotchas**
- Tools: `write_plan`, `read_plan`, `add_task`, `update_task_status`, `update_task_statuses`, `remove_task`; `enable_subtasks=True` adds `add_subtask`, `set_dependency`, `get_available_tasks` + `blocked`.
- Default store = fresh in-memory plan **per run**. The store is read before every request; a failing store fails the run.
- Survives compaction automatically (no pin needed).

### 3.9 Guardrails — `guardrails.md`
```python
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_ai_harness import GuardrailResult, InputGuardrail, OutputGuardrail, ToolGuardrail
from pydantic_ai_harness.guardrails import ToolCallInfo
from pydantic_ai_harness.guardrails.detectors import blocked_keywords, for_text, redact_secrets

def prod_needs_human(call: ToolCallInfo) -> GuardrailResult:
    return GuardrailResult.approve() if str(call.args.get('env', '')).startswith('prod') else GuardrailResult.allow()

agent = Agent('openai:gpt-6.1-sol', output_type=[str, DeferredToolRequests], capabilities=[
    InputGuardrail(guard=[redact_secrets, blocked_keywords(['internal-only'])]),
    OutputGuardrail(guard=for_text(redact_secrets)),
    ToolGuardrail(guard=prod_needs_human, tools=['deploy']),
])
```
**Gotchas**
- Input `block` → refusal response, no tokens; output `block` → raises `OutputBlocked`. Output `retry` needs `run()` (in `run_stream()` it raises `UnexpectedModelBehavior`). `approve` only for tool-arg guards.
- `InputGuardrail` checks only the user prompt; tool args/results need `ToolGuardrail` (`guard` before run, `result_guard` before the model). Result-guard `retry` re-runs side effects.
- Chains: `replace` threads forward (redactors first); a later `block` drops the redaction from history. Return `bool` or `GuardrailResult` (other truthy values deprecated).

### 3.10 Budget stack — `spend.md`, `tool-budgets.md`, `report-remaining-budget.md`, `wrap-up-at-limits.md`, `detect-loops.md`
```python
from decimal import Decimal
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits
from pydantic_ai_harness import DetectLoops, ReportRemainingBudget, SpendLimits, ToolBudgets, WrapUpAtLimits, wrapped_up_by
from pydantic_ai_harness.spend_limits import Budget

spend = SpendLimits(budgets=[Budget(usd=Decimal('1'), window='run'), Budget(usd=Decimal('20'), window='day')])
agent = Agent('anthropic:claude-sonnet-5-5', capabilities=[
    spend, ReportRemainingBudget(spend_limits=spend),
    ToolBudgets(per_tool={'web_search': 3}, total=20, refuse_repeats={'web_search'}),
    DetectLoops(), WrapUpAtLimits()])
result = agent.run_sync('Survey Python task queues.', usage_limits=UsageLimits(request_limit=10, tool_calls_limit=30))
print(result.output, wrapped_up_by(result.new_messages()))
```
**Gotchas**
- `SpendLimits` refuses the **next** request once a window is spent (`SpendLimitExceeded`): the crossing request completes and concurrent runs can overshoot. Default store is in-process; use `RedisSpendStore`/`PostgresSpendStore` across workers. `scope=lambda ctx: ctx.deps.tenant_id` for per-tenant; no ceiling = pure counter.
- For one run, core `UsageLimits(cost_limit=Decimal('5'))` may suffice. `WrapUpAtLimits` doesn't project `cost_limit`; default `request_limit` is 50.
- `DetectLoops` defaults (window 10; repeated_call 5, repeated_result 3, alternating 3, repeated_text 3) flag intentional polling; `action='error'` raises `LoopDetectedError`.

### 3.11 `CodeMode` — `code-mode.md`
```python
from pydantic_ai import Agent
from pydantic_ai_harness import CodeMode

agent = Agent('anthropic:claude-sonnet-5-5', capabilities=[CodeMode()])

@agent.tool_plain
def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    return {'city': city, 'temp_f': 72, 'condition': 'sunny'}

print(agent.run_sync("What's the weather in Paris and Tokyo, in Celsius?").output)
```
**Gotchas**
- `[codemode]` extra (pydantic-monty). Monty is a Python subset: no third-party imports, stdlib allowlist, `asyncio.gather` positional only.
- Select tools via `CodeMode(tools=[names] | predicate | {'code_mode': True})` (pairs with `FunctionToolset(...).with_metadata(code_mode=True)`); approval-required, external, deferred and shell tools stay native.
- FS/network only via `mount`, `os_access`, tools. `IPythonCodeMode` = full CPython with your permissions; never web-facing without a sandbox.

### 3.12 `CapabilityCreation` — `capability-creation.md`
```python
from pathlib import Path
from pydantic_ai import Agent
from pydantic_ai.workspaces import LocalWorkspaceBackend
from pydantic_ai_harness import CapabilityCreation

workspace = LocalWorkspaceBackend('.')
creation = CapabilityCreation(directory=Path('.authored'))
agent = Agent('anthropic:claude-sonnet-5-5', capabilities=[creation])

async def loop(prompts: list[str]):
    history = None
    for prompt in prompts:
        extra = await creation.load_active(workspace)   # live from the *next* run
        result = await agent.run(prompt, message_history=history, capabilities=extra, workspace=workspace)
        history = result.all_messages()
```
**Gotchas**
- Tools: `author_capability(name, code)`, `list_authored_capabilities()`, `disable_authored_capability(name)`; code must define exactly one no-arg `AbstractCapability` subclass. Saved as `<dir>/<name>.py` + `manifest.json`.
- Imports model-written Python **into your process** at authoring time (even if rejected). Requires writable `LocalWorkspace` + `'operator'` authority for `directory`. Gate with `ToolGuardrail(guard=lambda call: GuardrailResult.approve(), tools=['author_capability'])`; keep `directory` outside FileSystem's reach.
- Temporal/DBOS refuse run-time `capabilities=`, so this loop can't activate authored code there.

## 4. Experiment ideas

1. **Offline tour with `TestModel`**: `RepairToolArguments`, `ReportToolErrors`, `DetectLoops`, `ToolBudgets`; inspect `result.all_messages()` for injected parts (e.g. `LoopNudgePart`). Zero cost.
2. **Safe mini coding agent**: `DockerContainer(..., allow_internet_access=False)` + `FileSystem` + `Shell` + `Permissions('auto')` + `HandleDeferredToolCalls` + `RequireVerification` on a seeded buggy repo; then compare with plain `Coder()` in Logfire traces.
3. **Rebuild `Coder`** from its composition list (§3.1), then change one knob (allowlist, content hashes, add `Planning`) and measure turns/tokens.
4. **Compaction lab**: `TieredCompaction` + `ReportContextUsage` gauge; force `context_window=20_000`; add `StepPersistence` + `ConversationSearch` and ask about compacted-away facts.
5. **Multi-user memory**: `Memory(SqliteMemoryStore, namespace=...)` + `ArtifactScanner`; test isolation and try planting an injection.
6. **Planner/executor**: shared `SqlitePlanStore`, big model plans, small model executes with `enable_subtasks=True`; inspect the DB.
7. **Delegation**: `SubAgents` with per-delegate limits vs `DynamicWorkflow` on the same task; then `TaskControl` background tasks.
8. **Second-model safety net**: `ToolCallJudge(on_uncertain='ask')` + `ApprovalReviewer` on a fake `run_shell(requires_approval=True)`; tabulate blocked/approved/escalated.
9. **Crash & resume**: raise mid-tool, then `list_unresolved_tool_effects` + `continue_run`/`fork_run`; compare with `PGTaskDurability` or core Temporal.
10. **Self-extension**: `CapabilityCreation` + approval guardrail; have the agent author a tool and confirm it appears next iteration.

## 5. Key takeaways

- **Everything is a capability**; `Coder`/`Researcher` are just compositions — rebuilding them is the best tour of Pydantic AI's extension points.
- **The workspace is the hinge**: identical agent code runs locally or in Modal/E2B/Docker/k8s. Sandboxes outlive runs — persist `result.workspace.ref`, `destroy()` yourself.
- **Guardrails ≠ isolation**: FileSystem patterns, Shell allowlists, Permissions rules and bubblewrap are documented conveniences; real isolation = sandbox (VM > container).
- **Prompt-cache economics is a design theme**: memory injects only on change; reminders/plans/time are "cache-safe"; `ToolBridge`, `WarnOnCacheBusts` exist for caching; compaction knowingly trades cache for context.
- **Layered cost control**: core `UsageLimits` → `SpendLimits` (windows/tenants/shared stores) → soft controls (`ToolBudgets`, `ReportRemainingBudget`, `WrapUpAtLimits`, `DetectLoops`) that keep runs alive.
- **Second-model patterns recur**: judge (block), reviewer (approve), trajectory judge (steer), advisor (consult), router (pick), smart search (rank).
- **Persistence ≠ durability**: `StepPersistence` = snapshots you resume manually; AWS Lambda/Absurd/pgtask/Azure/Render + core Temporal/DBOS/Prefect = automatic replay.
- **0.x churn is real**: `DockerSandbox`→`DockerContainer`, `cwd=` args → workspace; read "Upgrading" sections in `coder.md`/`modal-sandbox.md`.
