# Troubleshooting

Symptoms first, then the usual causes. For each, what to try in order.

## Authentication fails

### `AADSTS530032` or `AADSTS7000116` during `bootstrap_auth.py`

Your tenant administrator has disabled device-code flow. Fallback: run the
auth on your laptop and forward the redirect port back to the server.

On the server, swap `DeviceCodeCredential` for `InteractiveBrowserCredential`
in `src/hyacine/graph/auth.py`, configured to listen on `127.0.0.1:8400`.
Then from your laptop:

```bash
ssh -L 8400:localhost:8400 <server>
```

Run `bootstrap_auth.py` on the server; the browser opens on your laptop and
the redirect flows back through the tunnel. This is a documented Azure
Identity pattern.

### `AADSTS50126`

Wrong password. Check Microsoft Entra sign-in logs.

### `AADSTS50158`

MFA challenge incomplete. Complete the Authenticator / TOTP step.

### `Persistence check failed`

MSAL probed for encrypted storage (`libsecret` / DBus) and failed. This project
forces unencrypted cache via `allow_unencrypted_storage=True` — if you see
this, confirm:

```bash
uv pip list | grep -i gobject
# should return nothing; PyGObject must NOT be installed
```

If `PyGObject` is installed, uninstall it:
```bash
uv pip uninstall pygobject
```

## Fetch fails

### `401 Unauthorized`

Token expired or revoked. Delete `./data/auth/` and
`~/.IdentityService/hyacine_cache*`, then re-run `bootstrap_auth.py`.

### `403 Forbidden`

Scope consent withdrawn. Re-run `bootstrap_auth.py`; during consent, verify
all four scopes appear (`User.Read`, `Mail.Read`, `Mail.Send`, `Calendars.Read`).

### `429 Too Many Requests`

Graph rate limit. The timer's `RandomizedDelaySec=2min` usually prevents this.
Wait 60 seconds and retry.

## LLM fails

### `CLAUDE_CODE_OAUTH_TOKEN is not set`

Environment file not loaded. Check:

```bash
systemctl --user show-environment | grep -i hyacine
```

Verify the `EnvironmentFile=` path in the unit matches where your `.env`
lives. Default: `~/hyacine/.env`.

### `claude subprocess timed out`

Bump `llm_timeout_seconds` in `./config/config.yaml`. Default 300 is usually
enough — if you hit this frequently, your fetch window is probably too large
(reduce `fetch_max_emails`).

### `claude returned an error`

Inspect the full error dict in the traceback. Common causes:

- **Daily usage cap hit** on your Claude Code subscription. Wait or upgrade.
- **Model name invalid**. Check `llm_model` in `config.yaml`.
- **Token revoked**. Regenerate with `claude setup-token`.

### Subprocess billed to the wrong account

`ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` leaked into the unit
environment. The unit's `UnsetEnvironment=` line should prevent this — check
that it's present and the shell profile that invoked `systemctl --user` did
not re-export these variables.

## sendMail fails

### `403 Forbidden`

`Mail.Send` scope not granted. Re-run `bootstrap_auth.py`; during the consent
step, all four scopes must be listed.

### `413 Payload Too Large` / `422`

HTML body too large. Usually indicates a runaway LLM response. Check the
`markdown` column in the database row and the corresponding prompt; consider
tightening the prompt's output format section.

## Host rebooted, daemon did not start

```bash
loginctl show-user $USER | grep Linger
```

Should report `Linger=yes`. If not:

```bash
loginctl enable-linger $USER
```

After reboot:

```bash
systemctl --user list-timers
```

The timer with `Persistent=true` shows the next fire time. If it missed today,
it fires on the next network-online event.

## Monitoring silent failures

The ops module (ntfy + healthchecks + error email) is intentionally
fail-closed — it never raises its own failures. Check journald directly:

```bash
journalctl --user -u hyacine-run.service --since "7 days ago" \
    | grep -iE "(httpx|connect|timeout|monitoring)"
```

## Path override issues

### Wizard cannot find existing config

Env vars override everything. Check:

```bash
env | grep -i hyacine_
```

Either unset the variables or re-run the wizard with `--overwrite`.

### `doctor.py` reports wrong mode on `.env`

```bash
chmod 600 ~/hyacine/.env
```

### `git pull` conflicts on `prompts/hyacine.md` or `config/config.yaml`

These paths are gitignored. If you have uncommitted local copies that
conflict, they were either committed by mistake in an earlier release or
your working tree has the old layout. Remove them and re-run the wizard:

```bash
cd ~/hyacine
rm -f prompts/hyacine.md config/config.yaml config/rules.yaml
python -m hyacine init
```
