# Standalone Form Agents

These modules are independent from `main.py` and directly integrate the two repos:

- `browser-use/browser-use` via Python SDK
- `vercel-labs/agent-browser` via CLI commands

## Static Configuration Used By Both Agents

- CV: `C:\mydesktop\resproj_thesis\job_predator\cv\cv.md`
- Cover letter PDF: `C:\mydesktop\resproj_thesis\job_predator\cover_letter\cover_letter_placeholder.pdf`
- LLM model: `gpt-5` (override with `LLM_MODEL_NAME`/`OPENAI_MODEL`)
- Embedding model: `text-embedding-3-large` (override with `EMBEDDING_MODEL_NAME`/`OPENAI_EMBEDDING_MODEL`)

## 1) browser-use Agent

Run:

```powershell
python -m agents.browser_use_live_form_agent "https://jobs.smartrecruiters.com/..."
```

If URL is omitted, it prompts.

Notes:

- Uses `Agent + Browser + ChatBrowserUse/ChatOpenAI` pattern from browser-use README.
- Reads API keys from `.env` and environment.
- Keeps browser alive and never submits the form.
- Writes run history/memory to `output/browser_use_form_memory.json`.
- Optional existing browser socket:
  - `BROWSER_USE_CDP_URL=http://127.0.0.1:9222`
- Training artifacts per run:
  - `output/learning_runs/browser_use/<timestamp_host>/run_log.md`
  - `conversation.md`, `model_actions.jsonl`, `model_outputs.jsonl`
  - `website_elements.md`
  - `screenshots/` (copied run screenshots when available)

## 2) agent-browser Agent

Run:

```powershell
python -m agents.agent_browser_live_form_agent "https://jobs.smartrecruiters.com/..."
```

If URL is omitted, it prompts.

Notes:

- Uses `open`, `snapshot -i`, refs, `fill`, `get value`, and persistent sessions from agent-browser README patterns.
- Keeps memory in `output/agent_browser_form_memory.json`.
- Uses persistent browser profile in `output/agent_browser_profile`.
- Optional existing browser socket/autodiscovery:
  - `AGENT_BROWSER_CDP=9222` (or websocket URL)
  - `AGENT_BROWSER_AUTO_CONNECT=1`
- Training artifacts per run:
  - `output/learning_runs/agent_browser/<timestamp_host>/run_log.md`
  - `commands.jsonl`, `decisions.jsonl`, `human_events.jsonl`, `state_snapshots.jsonl`
  - `snapshots/` (raw interactive snapshot + parsed fields)
  - `screenshots/` (normal + annotated periodic captures)

Performance + logging knobs (optional env):

- `FORM_AGENT_CAPTURE_EVERY_CYCLES` (default `2`)
- `FORM_AGENT_IDLE_BACKOFF_SECONDS` (default `3.0`)

## 3) Multi-Agent Orchestrator + Curator

Run any engine with one command:

```powershell
python -m agents.repo_multi_agent_learning_system agent-browser "https://jobs.smartrecruiters.com/..."
python -m agents.repo_multi_agent_learning_system browser-use "https://jobs.smartrecruiters.com/..."
```

Build compact learning memory from collected run logs:

```powershell
python -m agents.repo_multi_agent_learning_system --curate
```

Curated output:
- `memory/learning_memory.md`

## Whole-Repo Prompt

Reusable system prompt file:
- `docs/WHOLE_REPO_AGENT_PROMPT.md`
