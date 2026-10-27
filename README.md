# 🤖 LeetCoach MCP

An AI-powered LeetCode coach exposed as a **Model Context Protocol (MCP)** server.
It lets an AI assistant recommend problems, record attempts, analyze performance,
and build personalized interview-prep plans.

Everything runs **locally**: data lives in a single SQLite file on your machine,
with no server, no accounts, and no network calls at query time. The problem
catalog is scraped once from LeetCode's public GraphQL endpoint.

## ✨ Tools

| Tool | What it does |
| --- | --- |
| `recommend_problem` | Recommends 1–10 problems, weighted toward your weak topics, with a rationale for each pick. Filters: `topic`, `difficulty`, `exclude_solved`. |
| `log_attempt` | Records an attempt (`solved` / `attempted` / `skipped`), optional `time_taken_minutes` and `notes`, and updates your streak. |
| `analyze_performance` | Solve rate, per-topic accuracy, and timing over `7d` / `30d` / `90d` / `all`. Persists recomputed weak topics. |
| `generate_prep_plan` | A day-by-day, multi-week plan for a role (`general_swe`, `backend`, `frontend`, `data_ml`, `mobile`, `devops`) with spaced-repetition review days. |

## 📋 Requirements

- Python 3.11+
- No database server and no API keys

## 🚀 Install

```bash
git clone <this-repo> && cd Leetcode-MCP-Server
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## 📚 Seed the problem catalog

The MCP tools only read the local catalog, so seed it once:

```bash
python scripts/seed_catalog.py --limit 100   # quick smoke run
python scripts/seed_catalog.py               # full catalog
```

This writes `data/leetcode.db` (gitignored). Options: `--reset` to clear the
catalog first, `--include-paid`, `--delay`, `--page-size`, `--quiet`.

## ⚙️ Configure (optional)

Everything works with **zero configuration**. To override defaults, copy
`.env.example` to `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `LEETCOACH_DB_PATH` | `data/leetcode.db` | SQLite file path. |
| `LEETCOACH_DEFAULT_USER_ID` | a fixed built-in uuid | The user id attached to rows when a tool omits `user_id`. Keep it stable so streaks/history accumulate. |

## 🔌 Connect an MCP client

The server speaks **stdio** (it is launched by the client, not a background
service). Clients need the **absolute path** to the venv's console script —
print it with:

```bash
echo "$(pwd)/.venv/bin/leetcode-coach"
```

Every client below uses that path (shown here as `/ABS/PATH/.venv/bin/leetcode-coach`).

### Claude Desktop

Edit the config file, then fully restart Claude Desktop:

| OS | Path |
| --- | --- |
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "leetcode-coach": {
      "command": "/ABS/PATH/.venv/bin/leetcode-coach"
    }
  }
}
```

### Claude Code (CLI)

```bash
claude mcp add leetcode-coach -- /ABS/PATH/.venv/bin/leetcode-coach
claude mcp list          # verify it is registered
```

### Cursor

Global `~/.cursor/mcp.json`, or per-project `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "leetcode-coach": {
      "command": "/ABS/PATH/.venv/bin/leetcode-coach"
    }
  }
}
```

### VS Code (Copilot / Cline / Roo)

Create `.vscode/mcp.json` in your project:

```json
{
  "servers": {
    "leetcode-coach": {
      "type": "stdio",
      "command": "/ABS/PATH/.venv/bin/leetcode-coach"
    }
  }
}
```

### Any other stdio client

Use the `mcpServers` block from above, or launch the module directly:

```bash
python -m src.server
```

### Verify it works (no client needed)

This starts the server over stdio, performs the MCP handshake, and lists the
registered tools:

```bash
python - <<'PY'
import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    params = StdioServerParameters(command=sys.executable, args=["-m", "src.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for t in (await session.list_tools()).tools:
                print("-", t.name)

asyncio.run(main())
PY
```

Expected output: `recommend_problem`, `log_attempt`, `analyze_performance`,
`generate_prep_plan`.

## 🌐 Connect a web LLM (ChatGPT / Claude web) via ngrok

Desktop clients launch a local process over stdio, but **web** LLMs can only
reach a **public HTTPS URL**. So you run the server in HTTP mode and expose it
through a tunnel.

> ⚠️ The server has **no authentication**. Anyone with the URL can read and write
> your local database. Use a throwaway tunnel, and stop it when you are done.

### 1. Run the server in HTTP mode

```bash
source .venv/bin/activate
LEETCOACH_TRANSPORT=http LEETCOACH_PORT=8000 leetcode-coach
```

It now serves the MCP endpoint at `http://127.0.0.1:8000/mcp`. (Put these in
`.env` instead of exporting if you prefer.) Quick local check:

```bash
curl -s http://127.0.0.1:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}'
```

### 2. Expose it with ngrok

Install ngrok, then (one time) add your authtoken from
https://dashboard.ngrok.com/get-started/your-authtoken:

```bash
ngrok config add-authtoken <YOUR_TOKEN>
ngrok http 8000
```

Copy the `https://…` forwarding URL it prints and append `/mcp`, e.g.
`https://1a2b-3c4d.ngrok-free.app/mcp`. Leave both the server and ngrok running.

### 3. Add it in the web LLM

- **Claude web** — Settings → Connectors → *Add custom connector*, paste the
  `/mcp` URL. Leave authentication as **none**.
- **ChatGPT** — Settings → Connectors → *Add* (enable Developer mode first),
  paste the `/mcp` URL and choose **No authentication**.

Both features require a paid plan (Claude Pro/Max or ChatGPT Plus/Pro) and may
roll out gradually. If the connector reports an error, run the `curl` from step 1
to confirm the server is up, then re-check the exact URL.

### Notes

- A free ngrok URL **changes every restart** — update the connector URL to match.
- The `enable_dns_rebinding_protection=False` override in `src/server.py` is
  what stops the SDK replying `HTTP 421` to the tunnel's Host header. If you
  serve behind another hostname, remove/keep it accordingly.
- stdio stays the default; setting `LEETCOACH_TRANSPORT=http` only affects the
  process you launch with it.

## 💬 Example prompts

Once connected, just talk to the assistant:

- "Recommend a medium array problem I haven't solved."
- "I solved problem 1 in 20 minutes, log it."
- "I tried problem 2 but gave up after 30 minutes."
- "How am I doing over the last 30 days? What are my weak topics?"
- "Build me a 4-week backend interview prep plan, 1 hour a day."

## 🛠️ Troubleshooting

| Symptom | Fix |
| --- | --- |
| Tool says the problem isn't in the catalog | Run `python scripts/seed_catalog.py`. |
| Client doesn't show the server | Use the absolute path to `.venv/bin/leetcode-coach` and restart the client. |
| Progress/streak resets | Keep `LEETCOACH_DEFAULT_USER_ID` stable in `.env`. |
| Debug connection issues | Run the "Verify it works" snippet to isolate the server, then check your client's MCP logs. |

## 🧪 Tests

```bash
pytest          # runs against an in-memory SQLite database
ruff check .
```

## 🗂️ Layout

```text
src/
├── server.py            # registers the 4 tools, runs stdio
├── data/
│   ├── db.py            # SQLite query builder + client
│   ├── schema.sql       # problems, attempts, user_profile
│   └── scraper.py       # one-time LeetCode GraphQL scraper
├── services/            # recommendation, progress, analysis, planning
├── tools/               # thin MCP tool handlers
└── models.py            # pydantic input/output models
scripts/seed_catalog.py  # catalog seeder
```
