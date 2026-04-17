# Deploying to a server

This page covers deploying `hyacine` to a Linux server so the daily pipeline
runs automatically and the Web UI is reachable from your other devices.

Assumes you have already completed [ONBOARDING](ONBOARDING.md) on the same
host — that is, the wizard has run and Graph OAuth is bootstrapped.

## 1. Host prerequisites

- Linux (any reasonable distribution) with systemd.
- Python 3.11 or 3.12. If only 3.13 is present, `uv` will download 3.12.
- `uv` installed and on `PATH`.
- `git`.
- `claude` CLI installed and logged in via `claude setup-token`.
- A user-mode systemd session (`systemctl --user` works). If it returns
  "Failed to connect to bus", run:
  ```bash
  loginctl enable-linger $USER
  ```
  and reconnect.
- Outbound HTTPS to `login.microsoftonline.com`, `graph.microsoft.com`,
  `hc-ping.com`, `ntfy.sh`, and the endpoint Claude Code uses.
- An unused TCP port for the Web UI. Default is `8765`; change the unit file
  if that port is taken.

## 2. Install

```bash
git clone https://github.com/<user>/hyacine ~/hyacine
cd ~/hyacine
uv sync
python -m hyacine init
python scripts/bootstrap_auth.py
python scripts/doctor.py
```

Verify tests pass:

```bash
uv run ruff check . && uv run mypy src/ && uv run pytest -q
```

## 3. Secrets

`~/.config/hyacine/hyacine.env` (chmod 600) contains:

```bash
CLAUDE_CODE_OAUTH_TOKEN=<from `claude setup-token` on this host>
HYACINE_GRAPH_TENANT_ID=common
HYACINE_NTFY_TOPIC=<long random topic name, do not publish>
HYACINE_HEALTHCHECKS_UUID=<healthchecks.io check UUID>
```

Generate a fresh OAuth token per host so you can revoke each independently.
Both `ntfy.sh` and `healthchecks.io` offer free tiers that are more than
enough for a daily cadence.

## 4. systemd user units

The unit files live in `src/hyacine/ops/systemd/`. Install them:

```bash
mkdir -p ~/.config/systemd/user
cp src/hyacine/ops/systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hyacine-web.service
systemctl --user enable --now hyacine-run.timer
```

Verify:

```bash
systemctl --user list-timers hyacine-run.timer
systemctl --user status hyacine-web.service
```

Trigger a dry run without waiting for the daily firing:

```bash
systemctl --user start hyacine-run.service
journalctl --user -u hyacine-run.service -f
```

You should see `OK: sent=<id> emails=<N>` and receive a briefing in your
inbox.

## 5. Exposing the Web UI

The service binds `127.0.0.1:8765` without authentication — do not expose it
to the public internet as-is.

### Option A — Tailscale (recommended)

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Access from any tailnet device at `http://<host>.<tailnet>:8765`. No public
surface.

### Option B — Caddy reverse proxy with basic auth

```caddy
hyacine.internal.example {
    basicauth {
        <user> <bcrypt-hash>
    }
    reverse_proxy 127.0.0.1:8765
}
```

Generate the hash with `caddy hash-password`. Obtain a TLS cert via Caddy's
automatic ACME or an internal CA.

## 6. Updating

```bash
cd ~/hyacine
git pull
uv sync
systemctl --user restart hyacine-web.service
```

The timer does not need a restart unless the unit file itself changed. A
`daemon-reload` is only necessary if you modified unit files.

Your personal state in `~/.config/hyacine/` and `~/.local/state/hyacine/` is
untouched by `git pull`.

## 7. Backups

The SQLite database is small (kilobytes to megabytes). Simple nightly backup:

```bash
sqlite3 ~/.local/state/hyacine/hyacine.db \
    ".backup ~/hyacine-backups/hyacine-$(date +%F).db"
```

Retain as many snapshots as you like — a week or two covers any realistic
rollback scenario.

## 8. Revoking access

- **OAuth for Claude Code**: revoke via the Anthropic dashboard. Regenerate
  with `claude setup-token` and update `hyacine.env`.
- **Microsoft Graph tokens**: revoke the session via the Microsoft 365 admin
  console or your own account security page. Delete
  `~/.local/state/hyacine/auth/` and re-run `bootstrap_auth.py` to re-authorise.

## 9. Uninstall

```bash
systemctl --user disable --now hyacine-run.timer
systemctl --user disable --now hyacine-web.service
rm ~/.config/systemd/user/hyacine-{web,run}.*
systemctl --user daemon-reload

# Optional: remove all user data
rm -rf ~/.config/hyacine ~/.local/state/hyacine ~/.cache/hyacine

# Remove the code
rm -rf ~/hyacine
```
