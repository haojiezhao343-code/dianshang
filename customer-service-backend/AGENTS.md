# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Build & Run

```bash
# Install dependencies
uv sync

# Start the server (uvicorn)
uv run python main.py
```

- API docs auto-served at `http://<APP_HOST>:<APP_PORT>/docs`
- Configuration via `.env` file (loaded by `pydantic-settings`)

## Architecture Overview

This is an **LLM-powered e-commerce customer service backend** ("电商小二") built with FastAPI. The LLM acts as a deterministic decision router (temperature=0), not a creative chatbot — it decides which "track" to follow and emits structured commands. All business responses are template-driven with optional LLM rephrasing.

### Three-Track Dialogue System

Every user message is routed by the LLM into one (or more) of three tracks:
1. **task** — business operations (order status, logistics tracking, refunds)
2. **knowledge** — informational queries (refund policy, product info)
3. **chitchat** — casual conversation

If the LLM hits multiple tracks or none, the `ClarifyResponder` asks the user to be more specific.

### Request Processing Pipeline

```
POST /api/chat (ChatRequest)
  → chat_router converts to domain UserMessage
  → DialogueService.process_message()
      → DialogueStateRepository.load_state()     # deserialize from MySQL JSON
      → DialogueEngine.process_message()
          1. _prepare_session()                   # timeout/auto-create session
          2. _begin_turn()                        # create pending Turn
          3. Route by message type:
             TEXT:
               → TurnPlanner.predict()            # LLM: choose track + emit commands
               → TurnPlanValidator.validate()     # hallucination guard
               → TaskHandler.handle()             # if task track:
                   → CommandProcessor.run()       #   mutate DialogueState
                   → FlowExecutor.run_task()      #   advance YAML-defined flow DAG
               → ClarifyResponder.respond()       # if validation fails
             OBJECT:
               → Try to fill matching slots
               → Clarify if no active flow matches
          4. commit_turn() into session history
      → DialogueStateRepository.save_state()      # serialize back to MySQL
  → ChatResponse returned
```

### Key Modules

| Module | Purpose |
|---|---|
| `domain/` | Core Pydantic models: `DialogueState` (aggregate root), messages, task/system contexts |
| `engine/` | `DialogueEngine` — orchestrates the entire turn processing pipeline |
| `plan/` | `TurnPlanner` (LLM call for track/command selection), `TurnPlanValidator` (anti-hallucination), plan models |
| `task/command/` | Command types: `start_flow`, `set_slots`, `cancel_flow`, `resume_flow` + processing |
| `task/flow/` | YAML-defined flow DAGs: `FlowLoader`, `FlowExecutor`, step types (start/collect/action/end), link types |
| `task/action/` | Pluggable actions: `action_listen` (sentinel), `action_response` (static/rephrase/generate), custom actions (lookup order, logistics, recommend) |
| `clarify/` | `ClarifyResponder` — generates natural language clarification when LLM output is invalid |
| `infrastructure/` | Singleton LLM client, async MySQL engine, httpx async HTTP client |
| `repository/` | `DialogueStateRepository` — load/save full `DialogueState` as JSON blob in MySQL |
| `api/` | FastAPI routes, schemas, DI wiring (`dependencies.py` constructs entire object graph) |
| `prompts/` | Jinja2 templates for LLM prompts; `HistoryBuilder` serializes turns for prompt context |
| `flow_config/` | YAML definitions of all business flows (`user_flows.yml`) and system flows (`system_flows.yml`) |

### YAML Flow System

Business processes are defined as YAML DAGs with four step types:
- **start** — entry point
- **collect** — prompts user for a slot value; if missing, triggers a system collect flow (`system_collect_information`)
- **action** — executes a named action (e.g., `action_lookup_order_status`, `action_response`)
- **end** — terminates the flow

Links between steps support three types: `StaticLink` (always go to target), `ConditionalLink` (if/then), `FallbackLink` (else).

System flows (`system_task_started`, `system_task_interrupted`, `system_task_resumed`, `system_task_canceled`, `system_collect_information`) are interleaved between business task execution to provide transitional acknowledgements.

### DialogueState — The Aggregate Root

Persisted as a single JSON blob in MySQL (`dialogue_states` table, keyed by `sender_id`). Key fields:
- `active_task` — currently executing business task (flow_id, step_id, slots)
- `paused_tasks` — stack of interrupted tasks (LIFO: most recent paused restored first)
- `active_system_task` — currently executing system flow (takes priority over active_task)
- `sessions` / `current_session_id` — session history with 1-hour timeout auto-close
- `pending_turn` — in-progress turn (user msg + accumulating bot msgs)
- `focused_object` — last object (order/product) the user clicked in the frontend

### Actions & Registration

Built-in actions (`action_listen`, `action_response`) are manually registered. Custom actions in `task/action/custom/` are auto-discovered via `pkgutil` — any `Action` subclass defined in that package is automatically registered (no manual wiring needed when adding new actions).

### Slot System

Slots are key-value pairs stored in `active_task.slots`. The `CollectFlowStep` checks if a slot is already filled before prompting. Object messages from the frontend (order/product clicks) auto-fill matching slots (`order_number`, `product_id`). The `_eval_condition` method in `FlowExecutor` evaluates conditional links using `eval()` with `__builtins__: None` (sandboxed).

### External Dependencies

- **E-commerce service** at `COMMERCE_API_BASE_URL` — provides order status, logistics, product info APIs
- **LLM API** (OpenAI-compatible) — configured via `LLM_BASE_URL`/`LLM_API_KEY`; defaults to SiliconFlow/DeepSeek
- **MySQL** at `DATABASE_URL` — stores serialized dialogue state

## Key Conventions

- Chinese comments throughout the codebase (the project is Chinese-language)
- Python 3.12+ required
- All async I/O (FastAPI + async SQLAlchemy + httpx AsyncClient)
- Temperature=0 for LLM calls (deterministic routing, not creative generation)
- `uv` for package management
- Pydantic v2 models throughout (with `model_dump(mode="json")` for serialization)
- The `COMMAND_NAME_TO_CLASS` and `STEP_TYPE_TO_CLASS` dicts act as simple factory registries — extend these when adding new commands or step types