# First-run guide

This page walks you through a fresh install from `git clone` to receiving your
first hyacine report. Budget around 20 minutes.

## What you need first

- Python 3.11 or 3.12 on a Linux or WSL2 host (macOS works too; Windows native
  is unsupported today).
- [`uv`](https://docs.astral.sh/uv/) on `PATH`.
- A Microsoft 365 account with an Outlook mailbox you can sign into from a
  browser (any tenant — personal `@outlook.com` or organizational).
- Claude Code installed and logged in via `claude setup-token`. You will paste
  the resulting token into the wizard.
- Optional: accounts at `ntfy.sh` and `healthchecks.io` for out-of-band failure
  alerts. Both can be left blank at first and added later.

## 1. Clone and install

```bash
git clone https://github.com/lushuyu/Hyacine ~/hyacine
cd ~/hyacine
uv sync
```

Verify the tree is healthy:

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src/
```

All three should be green.

## 2. Run the wizard

```bash
python -m hyacine init
```

You will be asked, one field at a time:

| Field | Example | Notes |
|---|---|---|
| Name | `Alice` | Shown in the rendered prompt. |
| Role | `PM at Acme Robotics` | Shown in the rendered prompt. |
| Identity blurb | multi-line free text | 1-3 sentences. Finish with a blank line. |
| Priorities | repeated prompt | Things that promote mail to the "must do today" section. At least one. |
| Category hints | markdown bullet list | A sensible default is offered; press Enter to accept, or `E` to open `$EDITOR`. |
| Recipient email | `alice@example.com` | Where the daily report is delivered. |
| Timezone | IANA string | Validated via `zoneinfo`. Default `UTC`. |
| Language | `en` or `zh-CN` | Controls the rendered prompt's language. |
| Run time | `HH:MM` | Default `07:30`. Written into the systemd timer later. |
| Microsoft tenant id | `common` or a GUID | `common` works for any tenant. Override only if your tenant requires a single-tenant app registration. |
| OAuth token | paste your `claude setup-token` output | Hidden input. Pass `--no-prompt-token` to skip and fill in `.env` by hand later. |
| ntfy topic | blank or UUID | Create a long random topic name at <https://ntfy.sh>. Do not publish it. |
| healthchecks.io UUID | blank or UUID | Free tier plenty. Set `Cron: <your run_time>` with 30 min grace. |

The wizard writes these files (all inside the repo):

```
./.env                       (chmod 600 — secrets)
./config/config.yaml         (non-secret)
./config/rules.yaml          (copied from the starter set)
./prompts/hyacine.md         (rendered from the template)
```

Re-run the wizard any time. Existing files prompt for "update / backup & overwrite / skip".

## 3. Microsoft Graph OAuth (one-time)

```bash
python scripts/bootstrap_auth.py
```

A device-code URL and eight-character code are printed. Open the URL in any
browser, sign in with your Microsoft account, and approve the requested scopes
(`User.Read`, `Mail.Read`, `Mail.Send`, `Calendars.Read`). After MFA, the
script persists:

```
./data/auth/auth_record.json  (chmod 600)
```

and the MSAL token cache in `~/.IdentityService/` (a system-wide directory
managed by `msal-extensions` that cannot be relocated). Future runs are
silent — you only repeat this step if you revoke the session.

## 4. Health check

```bash
python scripts/doctor.py
```

This validates every expected path, permission, and environment variable.
Green = ready to run; any `!` indicates a problem that needs fixing before you
can continue.

## 5. First run

```bash
python scripts/test_sendmail.py --yes    # optional — fires one [TEST] email to your address
python -m hyacine run                    # the real run
```

The pipeline should print something like `OK: sent=<id> emails=<N>` and your
inbox should receive a message titled `Hyacine · YYYY-MM-DD` shortly after.

## 6. Web UI (optional but useful)

```bash
uv run uvicorn hyacine.web.app:app --host 127.0.0.1 --port 8765 --workers 1
```

Open <http://127.0.0.1:8765>. Four routes:

- `/` — run history
- `/runs/{id}` — rendered markdown for one run
- `/prompt` — edit the system prompt (Jinja-validated, snapshotted)
- `/rules` — edit classification rules (schema-validated, snapshotted)

## 7. Scheduling

See [server-deploy.md](server-deploy.md) for the systemd user units (web
service + daily timer) and the reverse-proxy options for exposing the Web UI
beyond `localhost`.

## Editing later

All user-owned content lives in the repo: `./.env`, `./config/`, and
`./prompts/hyacine.md`. You can edit the prompt or rules with the Web UI
(which snapshots each save for rollback) or directly in `$EDITOR` — both
paths are fine.

Secrets (`CLAUDE_CODE_OAUTH_TOKEN`, tenant id, ntfy topic, healthchecks UUID)
live in `./.env`. Keep mode `0600`.

## Common pitfalls

- **`ANTHROPIC_API_KEY` in shell profile**: silently overrides the Claude Code
  OAuth token and bills the wrong account. `doctor.py` warns if either
  `ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` is set at run time — clear them
  before invoking the pipeline.
- **`Persistence check failed`** during auth: your host has `libsecret` /
  `PyGObject` installed and MSAL is trying to use encrypted storage. The
  project forces unencrypted cache via `allow_unencrypted_storage=True`; make
  sure you have not installed `PyGObject` into the environment (`uv pip list | grep -i gobject`).
- **Tenant mismatch (`AADSTS530032` or `AADSTS7000116`)**: your tenant blocks
  device-code flow. Use an `InteractiveBrowserCredential` plus SSH local port
  forwarding — see [troubleshooting.md](troubleshooting.md).
- **Empty report**: check `fetch_max_emails` in `config.yaml` and confirm the
  watermark in `./data/hyacine.db` isn't ahead of `now` (happens if the system
  clock jumped).
