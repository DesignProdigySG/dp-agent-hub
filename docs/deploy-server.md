# Putting the Agent Hub on a server

This gets the hub running all the time on a small rented server, so your team can reach it from a
web address. It takes about an hour. You don't need to be a server expert, but you will type
commands into a terminal.

**Read this first.** Today the hub has *one shared admin password* and no per-person accounts.
Anyone who can reach it and knows the password can approve changes to Marketo. So the hub must
**never be open to the whole internet**. Step 6 puts a login in front of it. Don't skip it.

---

## What you need

- A credit card for the server (a small monthly cost; check the provider's current price)
- Your Anthropic API key and (for the finder agents) a Brave Search API key
- About an hour

Optional but recommended: a **domain name** you control (about US$10 a year). It lets you use
Cloudflare Access (step 6, option A), which gives the team a login screen.

---

## 1. Rent a server

Any of these work: **DigitalOcean**, **Hetzner**, **AWS Lightsail**.

Choose:
- **Ubuntu 24.04** (or 22.04)
- **2 vCPU and 4 GB of memory** (2 GB can work but is tight; the hub runs a database, a Python
  backend and a Node frontend)
- A region near your team (Singapore, if offered)
- **SSH key login** if the provider offers it (more secure than a password)

You'll get an IP address. Connect to it from your computer's terminal:

```bash
ssh root@YOUR_SERVER_IP
```

## 2. Basic safety

On the server:

```bash
apt update && apt upgrade -y
apt install -y ufw
ufw allow OpenSSH
ufw --force enable
```

This turns on a firewall that only allows SSH in. The hub's own ports are bound to the server
itself (not the internet), so nothing else is reachable until you add the tunnel in step 6.

## 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
docker --version
docker compose version
```

Docker is set to start on boot, and the hub's containers restart themselves (the compose file has
`restart: unless-stopped`).

## 4. Get the code

```bash
cd /opt
git clone YOUR_REPOSITORY_URL marketo-agent-hub
cd marketo-agent-hub
```

Use the URL of wherever this repository is hosted (GitHub, GitLab, ...). If the repository is
private, use a deploy key or a personal access token, as your provider describes.

## 5. Settings file

Make a `.env` file next to `docker-compose.yml`:

```bash
cp .env.example .env
```

Generate a database password and an encryption key:

```bash
openssl rand -hex 24                                  # use as POSTGRES_PASSWORD
openssl rand -base64 32 | tr '+/' '-_'                # use as HUB_SECRET_KEY
```

Edit `.env` (`nano .env`) and set **only these** (leave `DATABASE_URL` alone; Docker sets it):

```
POSTGRES_PASSWORD=<the first value>
HUB_SECRET_KEY=<the second value>
ADMIN_PASSWORD=<a long password you choose>
COOKIE_SECURE=true
VITE_ALLOWED_HOSTS=hub.yourcompany.com
```

- **Save `HUB_SECRET_KEY` somewhere safe** (a password manager). If you lose it, the API keys
  saved in the hub can't be read again.
- `VITE_ALLOWED_HOSTS` is the web address your team will use (set up in step 6). Without it the
  page shows "Blocked request".
- Don't put your Anthropic, Brave or Marketo keys here. Enter them in the hub's **Settings** page
  after signing in. They're stored encrypted.

Start everything:

```bash
docker compose up -d --build
docker compose ps
```

The first build takes several minutes. All three services (`postgres`, `backend`, `frontend`)
should show as running. If something fails, `docker compose logs backend` shows why.

At this point the hub works **on the server only** (`127.0.0.1`). Next, make it reachable safely.

## 6. Let your team in, safely

Pick one.

### Option A: Cloudflare Tunnel + Access (best for a team; needs a domain)

Cloudflare's free tier is meant for small teams (check their current limits). It gives you HTTPS
and a login screen, and you open no ports on the server.

1. Create a free Cloudflare account and add your domain to it.
2. Open **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel** → **Cloudflared**.
3. Cloudflare shows an install command with a token. Run it on the server.
4. Add a **public hostname**: `hub.yourcompany.com` → service type **HTTP**, URL
   `localhost:5180`.
5. Protect it: **Zero Trust** → **Access** → **Applications** → **Add** → **Self-hosted**.
   Use the same hostname. Add a policy that **allows only emails ending in `@yourcompany.com`**.
   The default "one-time PIN" login emails a code, so you don't need to set up Google sign-in.
6. Make sure the hostname matches `VITE_ALLOWED_HOSTS` in `.env`. If you change `.env`, run
   `docker compose up -d`.

Test it in a private browser window: you should get the Cloudflare login first, then the hub's
own sign-in.

### Option B: Tailscale (simple; no domain; everyone installs an app)

Tailscale makes a private network between your team's devices and the server.

1. Make a Tailscale account, then on the server:
   ```bash
   curl -fsSL https://tailscale.com/install.sh | sh
   tailscale up
   tailscale serve --bg 5180
   ```
2. In the Tailscale admin page, enable **HTTPS certificates** (DNS settings).
3. The server gets an address like `hub.your-tailnet.ts.net`. Put that in `VITE_ALLOWED_HOSTS`,
   then `docker compose up -d`.
4. Each colleague installs Tailscale and you invite them to your tailnet. Check Tailscale's
   current free-plan user limit before you count on it for a whole team.

## 7. First sign-in

Open your hub address. Sign in with the `ADMIN_PASSWORD` you set. Then, in **Settings**:

1. **LLM router**: paste your Anthropic key and press **Test**.
2. **Web search**: paste your Brave key.
3. **Marketo**: leave on `demo` until you're ready to connect a **sandbox**.

Install the sample agents on the server:

```bash
cd /opt/marketo-agent-hub
for p in data_doctor data_health_scan designer lead_finder icp_finder; do
  docker compose exec backend python -m app.presets $p
done
```

Agents you made on your laptop don't move across. The server starts fresh, so install or recreate
them here.

## 8. Backups

The database holds your agents, tasks and history. Back it up daily:

```bash
mkdir -p /opt/backups
crontab -e
```

Add this line (runs at 3am every day, keeps the files in `/opt/backups`):

```
0 3 * * * cd /opt/marketo-agent-hub && docker compose exec -T postgres pg_dump -U hub hub | gzip > /opt/backups/hub-$(date +\%F).sql.gz
```

Copy those files off the server now and then (to Google Drive or another machine). A backup on
the same server doesn't help if the server is lost. Also keep a copy of `.env`, especially
`HUB_SECRET_KEY`.

## 9. Updating the hub later

```bash
cd /opt/marketo-agent-hub
git pull
docker compose up -d --build
```

Database changes apply automatically on start-up.

---

## If something goes wrong

| Problem | What to check |
|---|---|
| Page says "Blocked request" | `VITE_ALLOWED_HOSTS` doesn't match the address you typed. Fix `.env`, run `docker compose up -d`. |
| Can't sign in / cookie problems | You're on HTTPS but `COOKIE_SECURE` isn't `true`, or the reverse. |
| Containers won't start | `docker compose logs backend` (or `postgres`, `frontend`). |
| Server rebooted and the hub is down | `docker compose ps`. They should restart by themselves; if not, `docker compose up -d`. |
| Lost `HUB_SECRET_KEY` | Saved API keys in Settings can't be read. Enter them again after setting a new key. |
| Agents' tasks fail straight away | No Anthropic key in Settings, or it's wrong. |

## What this does not give you yet

- **Individual accounts.** Everyone shares the one admin password, and approvals aren't tied to
  a person. Cloudflare Access at least records who reached the hub.
- **Roles.** Anyone signed in can edit any agent and see Settings.

Both are planned as the next step.
