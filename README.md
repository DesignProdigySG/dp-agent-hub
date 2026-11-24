# DP Agent Hub (starter)

## 1. What this is

The DP Agent Hub is a web app where AI agents do work for you and you stay in control. You give an agent a job (instructions, the Marketo tools it may use, reference documents), hand it tasks on a board or a calendar, and it works through them. Before anything changes in Marketo, the agent stops and asks. You can approve, edit the change, approve part of it, or send it back with a note. A 3D office shows your agents walking between the Database, Campaigns, Design Studio and Break Room as they work, and an Insights page tracks what they did and what it cost. It was cloned from Josh's Marketo Agent Hub  starter and expanded to be a more general-purpose Agent Hub

This is a starter. It has no ready-made agents tied to a particular company. Clone it, connect your Marketo sandbox, and build your own agents, either on the Agents page or by asking Claude Code to change the code.

![The 3D office with two agents](docs/office.png)

The task board, with a few scheduled tasks:

![The task board](docs/board.png)

It also runs without Marketo. In **demo mode** (the default), agents work against an in-memory stand-in for Marketo with a few hundred fictional leads. You can try everything safely before you connect a real instance.

---

## 2. What you need

| Tool | Why | Get it | Check it's installed |
|---|---|---|---|
| A Marketo instance | The hub works on it. **Use a sandbox.** Agents can change real data once you approve. | Ask your Marketo admin or Adobe account team for sandbox access | You can sign in and open Admin |
| An Anthropic API key | Agents need a language model to think. Claude is the default. | [console.anthropic.com](https://console.anthropic.com/) → API Keys | The key starts with `sk-ant-` |
| Docker Desktop | Runs the Postgres database | [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/) | `docker --version` |
| Python 3.12 | Runs the backend | [python.org/downloads](https://www.python.org/downloads/) (macOS: `brew install python@3.12`) | `python3.12 --version` |
| Node.js 22 LTS (20.19 or newer works) | Runs the frontend | [nodejs.org](https://nodejs.org/) | `node --version` |
| git | Gets the code and tracks your changes | [git-scm.com/downloads](https://git-scm.com/downloads) | `git --version` |
| VS Code | Editor | [code.visualstudio.com](https://code.visualstudio.com/) | Opens |
| Claude Code | AI assistant that can read, run and change this project | [VS Code extension](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code) and/or the CLI: [docs.anthropic.com/en/docs/claude-code](https://docs.anthropic.com/en/docs/claude-code/overview) | `claude --version` (CLI) |

**Other language models.** The LLM router also supports OpenAI (`openai/...`), Google Gemini (`gemini/...`), Azure OpenAI (`azure/...`) and local models through Ollama (`ollama/...`). Set the model for each tier (fast, standard, strong) and the matching key in **Settings → LLM router**.

Run the "Check it's installed" commands in a terminal. On macOS that's the Terminal app. In VS Code you can use **Terminal → New Terminal**.

---

## 3. Get the code and open it in VS Code

1. Clone the repository:

   ```bash
   git clone https://github.com/jdarring/marketo-agent-hub-starter.git marketo-agent-hub
   cd marketo-agent-hub
   code .
   ```

   If `code` isn't found, open VS Code and choose **File → Open Folder…**, or run **Shell Command: Install 'code' command in PATH** from the Command Palette (⇧⌘P / Ctrl+Shift+P).

2. Install the Claude Code extension. Open the Extensions view (⇧⌘X / Ctrl+Shift+X), search for **Claude Code** (publisher: Anthropic) and click **Install**.

3. Sign in. Click the Claude icon in the sidebar (or run **Claude Code: Open** from the Command Palette) and follow the prompts. You can sign in with a Claude subscription or an Anthropic Console account. If you prefer the terminal, run `claude` in the project folder.

---

## 4. Run it locally

You can let Claude Code do the setup. Open Claude Code in the project and ask:

> Set up this project and start it locally.

It will read this README and run the steps below. To do it yourself:

### 4.1 Settings file

```bash
cp .env.example .env
```

You don't have to edit anything yet. Most settings (Marketo, LLM keys, notifications) are entered later on the **Settings** page. They're stored encrypted in the database.

### 4.2 Database (Postgres in Docker)

Start Docker Desktop, then:

```bash
docker compose up -d postgres
```

This starts Postgres 17 with pgvector on `localhost:5442`, which matches `DATABASE_URL` in `.env`. To skip Docker while you try things out, leave `DATABASE_URL=` empty in `.env` and the hub uses a SQLite file in `backend/data/`. SQLite is for development only.

### 4.3 Backend (Python, port 8000)

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --reload --port 8000
```

On Windows, use `.venv\Scripts\pip` and `.venv\Scripts\uvicorn`.

Leave this terminal running.

### 4.4 Frontend (Node, port 5180)

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5180**.

### 4.5 First sign-in

The first time the backend starts, it prints a one-time code in the backend terminal:

```
No admin password is set. First-run setup code: XXXX-XXXX-XXXX
```

Enter the code in the browser and choose the admin password. To skip this step, set `ADMIN_PASSWORD=` in `.env` before the first start.

Then open **Settings → LLM router**, paste your Anthropic API key and press **Test**.

### 4.6 Optional: install the two sample agents

Two agents come as code-defined presets. Neither contains company-specific content:

```bash
cd backend
.venv/bin/python -m app.presets data_doctor        # a Data Doctor that checks and fixes lead data
.venv/bin/python -m app.presets data_health_scan   # adds the full 7-dimension data health scan to it
.venv/bin/python -m app.presets designer           # a Designer for landing pages, forms and emails
```

The Designer can use your brand guidelines, colours and approved images. See [backend/brand/README.md](backend/brand/README.md).

### 4.7 Everything in Docker (alternative)

```bash
docker compose up --build
```

This runs Postgres, the backend and the frontend together on the same ports.

---

## 5. Connect Marketo

The hub talks to Marketo in three ways. All three use the same API credentials:

- **REST API** (`https://<munchkin>.mktorest.com/rest/v1/...`): leads, lists, activities, campaigns.
- **Asset API** (`/rest/asset/v1/...`): programs, emails, landing pages, forms, folders, tokens, segmentations, snippets.
- **Adobe's Marketo MCP server** (`https://marketo-mcp.adobe.io/mcp`): a large set of ready-made Marketo tools (smart campaigns, smart lists, forms, programs and more).

### 5.1 Create an API role

In Marketo: **Admin → Users & Roles → Roles → New Role**. Name it, for example, *Agent Hub API*. Tick **Access API**, then under it tick the permissions your agents need. This is what the hub's tools use:

| Permission | Used for |
|---|---|
| Read-Write Lead (and Read-Write Person, if shown) | Reading and updating leads, merging duplicates, adding to and removing from static lists, lead field descriptions |
| Read-Only Activity | Activity history, activity types, the activity feed and the data health scan (including bulk activity export) |
| Read-Write Assets | Asset API tools: reading and creating programs, emails, templates, landing pages, forms, folders, tokens, snippets, segmentations; the Designer's publish tools |
| Read-Write Campaign | Smart campaign and smart list tools from the MCP server |
| Execute Campaign | Requesting (triggering) a smart campaign for leads |

Some instances also list **Approve Assets** or **Activate Campaign**. Add them only if you want agents to approve assets or activate campaigns. Even with these permissions, the agents ask you first.

If you only want to look around, start with the **Read-Only** versions. Write tools will then fail with error 603 until you upgrade the role.

Also give the role access to the **workspaces** the agents should work in (the workspace permissions on the role).

### 5.2 Create an API-only user

**Admin → Users & Roles → Users → Invite New User**. Give it a name such as *agent-hub@yourcompany.com*, tick **API Only**, and choose the role from 5.1.

### 5.3 Create a LaunchPoint custom service

**Admin → Integration → LaunchPoint → New → New Service**. Choose **Custom** as the service, give it a display name such as *Agent Hub*, and pick the API-only user. Save.

### 5.4 Find your credentials

| You need | Where to find it in Marketo |
|---|---|
| Client ID and Client Secret | **Admin → LaunchPoint** → your service → **View Details** |
| Munchkin ID (looks like `123-ABC-456`) | **Admin → Integration → Munchkin** |
| REST endpoint (for reference) | **Admin → Integration → Web Services → REST API → Endpoint**. The hub builds it from the Munchkin ID as `https://123-ABC-456.mktorest.com`. |

### 5.5 Enter them in the hub

1. Open **Settings → Marketo**.
2. Set **Mode** to `live`.
3. Fill in **Munchkin ID** and **Client ID**, and click **Set** next to **Client secret** to paste it.
4. Leave **MCP server URL** as `https://marketo-mcp.adobe.io/mcp`.
5. Press **Test**. The hub requests a REST access token and loads the MCP tool list, and shows the result of each.

Never paste the client secret, API keys or passwords into a chat (including Claude Code). Enter them in **Settings** or in `.env`, which git ignores. The Settings page stores them encrypted and never sends them back to the browser.

### 5.6 The Marketo MCP server

The hub connects to Adobe's Marketo MCP server over streamable HTTP. It sends the same LaunchPoint credentials as headers (`X-Marketo-Munchkin-Id`, `X-Marketo-Client-Id`, `X-Marketo-Client-Secret`). Nothing else is needed. Check with your Adobe team that the MCP server is available for your instance.

The MCP tools are loaded when the hub connects. They appear on each agent's **Tools** card under the **Marketo MCP** tab. If they can't be loaded, the Agents page says so (*Could not load Marketo MCP tools: ...*), and the **Hub** and **Marketo REST** tools still work. In demo mode, a small built-in stand-in for the MCP tools is used.

### 5.7 Marketo address for links

So that agents can link to what they create or change, fill in **Settings → Marketo → Marketo address for links**. Open any program in Marketo and copy the address up to, but not including, the code that starts with `ME` or `PG`. For example:

```
https://experience.adobe.com/#/@yourorg/so:123-ABC-456/marketo-engage/
```

or, on the classic address:

```
https://app-ab12.marketo.com/#
```

### 5.8 When Marketo says no (603)

Error 603 means the API user's role doesn't allow that call. The hub handles the common cases:

- **List membership checks** (`ismember`). If refused, the hub reads the list's members instead.
- **Bulk activity export.** Some roles and instances refuse it (603, or quota errors 1029/1035). The data health scan then pages through the REST activities API.
- **Campaign requests and Asset API calls.** If refused, the agent gets a plain explanation of which permission is missing, so it can tell you.

---

## 6. Your first agent

This example builds a **Lead Data Checker** that finds leads with a missing or messy country and proposes fixes for you to approve.

1. Open **Agents → New agent**.
2. **Profile.** Name: *Lead Data Checker*. Role: *Proposes fixes to lead country data*. Home zone: *The Database*. Model tier: *Standard*. Pick a character and a colour.
3. **Instructions.** Paste something like:

   ```markdown
   You check lead data quality in Marketo.

   ## Your job
   - Find leads whose Country is empty or not a full country name (e.g. "USA", "U.S.", "DE", "uk").
   - Propose the standard value (e.g. "United States", "Germany", "United Kingdom").
   - Only fix values you are certain about. List anything unclear for a person.

   ## Rules
   - Read first. Say how many leads a change touches before you make it.
   - Update at most 50 leads per change.
   - Never change email addresses, scores or program statuses.

   ## Report
   A short summary, then a table: lead ID, old value, new value.
   ```

4. **Tools.** On the **Hub** tab, pick `recent_activities`. On the **Marketo REST** tab, pick `rest_get_leads` (read) and `rest_update_leads` (write). Keep the list short: an agent with fewer tools makes fewer mistakes.
5. **Approvals.** Choose **Approve every change**. Reads run freely, and every update pauses for you.
6. **Knowledge (optional).** On **Agents → Knowledge**, add a document such as *Our data standards* (a list of approved country names, state codes and title rules). Attach it to the agent on its **Knowledge** card. The agent searches it while it works.
7. **Skills (optional).** On **Agents → Skills**, add reusable playbooks, for example *How we normalise job titles*, and attach them. An agent loads a skill only when it needs it.
8. **Default task (optional).** Give it a default task such as *Check this week's new leads* so you can start it in one click.
9. **Save changes.**

Now give it work. Click **+** (New task), pick the agent, and write the task, for example *Check the country field on leads created in the last 7 days*. Watch it on the **Board** or in the **Spatial** view. When it wants to update leads, the task moves to **Needs approval**. Open the approval to see every change. You can then:

- **Approve** it as it is,
- **edit** the values before approving,
- **approve some** items and send the rest back, or
- **request changes** with a note. The agent reads the note and tries again.

You can also put a task on the **Calendar**, make it repeat, or attach files (a CSV of lead IDs, a brief) for the agent to read.

---

## 7. Making it yours with Claude Code

Claude Code can read this whole project, explain it, change it, run the tests and start the app. You describe what you want in plain words. You don't need to know where the code lives.

### How to ask

Open Claude Code in VS Code (or run `claude` in the project folder) and type a request. Good requests:

- **Say what you want and why.** For example: "so that marketing ops can see at a glance whether the database is getting cleaner".
- **Name the Marketo objects.** Program, smart campaign, static list, token, field API names such as `leadSource`.
- **Say how it should behave around approvals.** Should it pause before writing? Is anything off-limits?
- **Ask it to test.** "Add a test and run the backend and frontend tests."

### Example prompts

1. > Add a hub tool that lets agents request a Marketo smart campaign by name for a list of lead IDs. It should look up the campaign by name, refuse if it isn't a requestable campaign, and always pause for approval. Add tests.

2. > Add a "Webinar Producer" agent preset that clones my webinar program template (a program named "TEMPLATE - Webinar") into a folder I choose, and fills in its My Tokens (Webinar Title, Date, Speaker, Registration URL) from the task description. Every Marketo write should need approval.

3. > Show approval requests in Microsoft Teams as well as by email. Add the settings to the Settings page, send an Adaptive Card with the same Approve / Reject / Review links the email uses, and add tests. See the note at the top of backend/app/notify.py.

4. > Add a KPI to the Insights page that shows how many leads the agents updated each day this month, with a comparison to last month.

5. > Change the colours of the 3D office zones and the app's primary colour to our brand: navy #0B2545, teal #13A89E, sand #EEE3CF.

6. > Write a test for the hand-off between two agents: when the first agent hands off with three lead IDs, the second agent's task should include those IDs. Run the backend tests.

7. > Why did my agent fail? Here's the task ID: tsk_1234abcd. Look at the task's result, the audit log and the backend output, and explain in plain words what went wrong and how to fix it.

8. > Add a "Smart List Auditor" agent preset that reads every smart campaign in a folder I give it and reports campaigns with no smart list filters, triggers on "Data Value Changes" with no constraint, or flows that send an email with no wait step. Read-only: no write tools.

9. > Put our brand into backend/brand: here are our colours and fonts [paste them]. Create brand.json and design_system.md as the brand README describes, then reinstall the Designer preset.

10. > When the Data Doctor finishes a data health scan, hand the 20 best leads to an agent called "Router" with a task to add them to the static list "Sales follow-up". Explain the change before you make it.

11. > Explain how approvals work in this codebase, from the moment an agent calls a write tool to the moment the change reaches Marketo. Point me to the files.

12. > Add a setting to cap how many leads any one agent can update per day, and stop the agent with a clear message when it reaches the cap.

### Tips

- **Be specific.** "Add a tool that removes leads from a static list, with approval" works better than "make list tools better".
- **Ask for a plan first** on bigger changes: "Plan this before writing code." Read the plan and correct it.
- **Ask it to run the tests** (`pytest` and `ruff` for the backend; `npm run lint`, `npm test` and `npm run build` for the frontend). They all run without Marketo or an LLM key.
- **Review the diff.** VS Code's Source Control view shows every change. Ask Claude Code "what did you change and why?" if anything is unclear.
- **Commit often**, so you can go back: "Commit this with a short message." Use a branch for experiments.
- **Use a sandbox.** Try new agents in demo mode first, then on your Marketo sandbox. Production comes last.
- **Never paste secrets into the chat.** Put keys and passwords in **Settings** or `.env`. If Claude Code needs a secret to test something, tell it where the secret is stored rather than pasting it.

---

## 8. Project layout

```
backend/                 Python (FastAPI + LangGraph)
  app/main.py            app start-up and the live event stream (/ws)
  app/config.py          settings (.env defaults); app/settings_store.py: the Settings page
  app/hub.py             runs agents, the scheduler, approvals and resumes
  app/agents/            agent definitions (registry), the agent loop (custom.py), all tools (tools.py)
  app/marketo/           REST client, Asset API, MCP client, rate governor, demo stand-in (gateway.py), links
  app/llm/               the LLM router (tiers, fallbacks, budget, cost tracking)
  app/workflows/         code-defined workflows, e.g. data_health (the full data health scan)
  app/presets.py         ready-made agents (data_doctor, data_health_scan, designer)
  app/preset_text/       the presets' instructions and skills, in Markdown
  app/design.py          the Designer's tools: brand check, previews, publish email / landing page
  app/notify.py          email approval notifications (add other channels here)
  app/routes/            the HTTP API used by the frontend
  brand/                 your optional brand pack for the Designer (see its README)
  migrations/            database schema changes (Alembic)
  tests/                 the backend tests (pytest)
frontend/                React + TypeScript (Vite)
  src/views/board/       task board, task dialogs, results
  src/views/calendar/    calendar
  src/views/spatial/     the 3D office (react-three-fiber)
  src/views/agents/      Agents, Skills and Knowledge pages
  src/views/insights/    Insights page and charts
  src/views/settings/    Settings page
  src/components/        approval dialog, Markdown editor, shared UI
  src/store/, src/lib/   app state, API and WebSocket clients
docker-compose.yml       Postgres (and optionally the whole app)
.env.example             settings you can set before start-up
```

---

## 9. Troubleshooting

**The Marketo MCP tools don't show up.** Press **Test** in **Settings → Marketo** and read the MCP line. Check that Mode is `live`, the Munchkin ID, Client ID and Secret are right, and the MCP server URL is `https://marketo-mcp.adobe.io/mcp`. Check with Adobe that the MCP server is available for your instance. The Hub and REST tools keep working in the meantime.

**601 or 602 (access token invalid or expired).** The hub gets a new token and retries automatically. If it keeps happening, the Client ID or Secret is wrong, or the LaunchPoint service was deleted or its user deactivated.

**603 (access denied).** The API role is missing a permission or workspace access. See 5.1 and 5.8. The error message names the call that was refused.

**606 or 615 (rate or concurrency limit), or the daily quota.** Marketo allows 100 calls per 20 seconds, 10 at once, and a daily quota. One rate governor sits in front of every REST and MCP call and keeps the hub under those limits, and it retries 606/615. If another integration shares your quota, lower the limits in **Settings → Rate governor**. The speed meter in the top bar shows current use.

**1029 or 1035 (bulk export quota or limit).** The data health scan switches to REST paging on its own. It's slower, but it finishes.

**"Port 5442 is already in use" when starting Postgres.** Another Postgres or container is using it. Change the left-hand port in `docker-compose.yml` (for example `"127.0.0.1:5443:5432"`) and the port in `DATABASE_URL` in `.env` to match.

**Port 8000 or 5180 is in use.** Stop the other app, or start the backend with a different `--port`. The frontend's port is set in `frontend/vite.config.ts`. If you change the backend port, start the frontend with `BACKEND_URL=http://127.0.0.1:<port> npm run dev`.

**Agents' tasks fail straight away.** Most likely no LLM key is set. Open **Settings → LLM router**, add the key and press **Test**.

**Start again with an empty database.**

- Postgres: `docker compose down -v`, then `docker compose up -d postgres`. This deletes all hub data: tasks, agents, settings and history.
- SQLite: stop the backend and delete the `backend/data/` folder.

Either way you'll get a new first-run setup code. Keep `backend/data/secret.key` (or set `HUB_SECRET_KEY`) if you want saved secrets to stay readable.

**Still stuck?** Ask Claude Code: "The backend shows this error: [paste the error, minus any secrets]. What's wrong?"

---

## 10. Development notes

```bash
cd backend && .venv/bin/pytest -q && .venv/bin/ruff check app tests
cd frontend && npm run lint && npm test && npm run build
```

The tests use SQLite and the demo Marketo stand-in, so they need no credentials. To run them against Postgres, point `TEST_DATABASE_URL` at a scratch database you created for the purpose. Never use your real hub database: the tests empty its tables.

**Schema changes.** Postgres is managed by Alembic, and the backend runs `upgrade head` on start-up. After changing a model in `backend/app/db.py`:

```bash
cd backend && DATABASE_URL=postgresql://hub:hub_dev_only@127.0.0.1:5442/hub \
  .venv/bin/alembic revision --autogenerate -m "describe the change"
```

**Event contract.** Messages from the server to the browser are defined in `backend/app/events/schema.py`. After changing them, run `npm run gen:types` in `frontend/`.

---

## Licence

Licence: to be added.

3D agents and environment: [Kenney](https://kenney.nl) Mini Characters and Brick Kit (CC0). The licence files sit next to the models in `frontend/public/assets/kenney/`. The hub's own cast in `frontend/public/assets/characters/` is built on the Kenney character rig.
