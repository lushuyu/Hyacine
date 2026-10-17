# Troubleshooting

Symptoms first, then the usual causes. For each, what to try in order.

## Authentication fails

### `AADSTS530032`, `AADSTS7000116` or `AADSTS530036`

Your tenant blocks device-code flow. `AADSTS530036` on refresh ("the token
will never be usable and should be deleted") comes from a Conditional Access
"authentication flows" policy. Switch to the authorization-code flow: set

```bash
HYACINE_GRAPH_AUTH_MODE=interactive_browser
HYACINE_GRAPH_REDIRECT_PORT=8400   # optional, default 8400
```

in `./.env`, then open a tunnel from the machine that has the browser:

```bash
ssh -L 8400:localhost:8400 <server>
```

Over that session run `python scripts/bootstrap_auth.py --reset`. It prints
the sign-in URL; open it locally and the redirect comes back through the
tunnel. `python scripts/bootstrap_auth.py --check` later verifies the cached
token without ever prompting.

The scheduled run never starts an interactive login: with a dead refresh
token it fails at once with `AuthenticationRequiredError` (and alerts)
instead of waiting on a prompt no one can see. Re-run `bootstrap_auth.py`.

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

> The subsections below are for the default **Claude Code OAuth** provider
> (api_format `anthropic_cli`). If you've picked a different provider,
> skip to [Other providers](#other-providers) first — the error will look
> like `HTTP 401: invalid_api_key`, `Connection refused` (Ollama), etc.,
> not a `claude` subprocess error.

### `CLAUDE_CODE_OAUTH_TOKEN is not set`

Environment file not loaded. Check:

```bash
systemctl --user show-environment | grep -i hyacine
```

Verify the `EnvironmentFile=` path in the unit matches where your `.env`
lives. Default: `~/hyacine/.env`.

### `claude subprocess timed out`

Bump `llm_timeout_seconds` in `./config/config.yaml`. Default 300 is usually
enough — if you hit this frequently, your fetch window is probably too large.
The fetch reads at most 10 pages of 100 messages per window, newest first,
and logs a `fetch_emails hit the 10-page cap` warning when older mail is left
out (`journalctl --user -u hyacine-run | grep 'page cap'`). `fetch_max_emails`
is not enforced yet. After a long outage you can shrink the catch-up window
by moving the watermark (a UTC ISO-8601 timestamp) forward:

```bash
sqlite3 ./data/hyacine.db \
    "UPDATE watermarks SET value='2026-10-17T00:00:00+00:00' WHERE key='last_successful_run_at';"
```

Keep `llm_timeout_seconds` well below the run unit's `TimeoutStartSec=40min`,
or systemd stops the run before the LLM call gives up.

### `claude returned an error`

Inspect the full error dict in the traceback. Common causes:

- **Daily usage cap hit** on your Claude Code subscription. Wait or upgrade.
- **Model name invalid**. Check `llm_model` in `config.yaml`.
- **Token revoked**. Regenerate with `claude setup-token`.

### Tuning the `claude -p` run: effort and safe mode

The CLI provider pins two Claude Code settings through the environment so the
daily run doesn't depend on how you use Claude Code interactively on the same
host:

- `CLAUDE_CODE_EFFORT_LEVEL` comes from `HYACINE_CLAUDE_EFFORT` in `./.env`
  (`low` / `medium` / `high` / `xhigh` / `max`, default `high`). Lower it if
  runs get slow, raise it if the digest misses nuance. The Anthropic Console
  provider reads the same variable for current models.
- `CLAUDE_CODE_SAFE_MODE=1` stops the run from loading your `~/.claude`
  customizations — CLAUDE.md, hooks, plugins, MCP servers, output styles.
  Auth and model selection work as usual. Set `HYACINE_CLAUDE_SAFE_MODE=0`
  only if the run genuinely needs one of those.

The subprocess also runs from an empty temporary directory, so it doesn't pick
up the checkout's git status or a project-level CLAUDE.md.

### `FileNotFoundError: 'claude'` under systemd

systemd user units run with a minimal default PATH that excludes
`~/.local/bin`, where the official Claude Code installer drops the binary.
The shipped `hyacine-run.service` template pins `Environment=PATH=` to
include it. If you're on an old copy, either redeploy the unit or set
`HYACINE_CLAUDE_BIN=/absolute/path/to/claude` in `./.env`.

### Subprocess exits with empty stdout/stderr (SIGTRAP)

`claude` 2.1.x ships as a single ELF binary with embedded JIT.
`MemoryDenyWriteExecute=true` in the systemd unit traps the runtime when it
tries to mark JIT pages writable+executable, killing the process with
SIGTRAP and no diagnostics. The shipped template leaves MDWE off — if you
hand-rolled your unit, comment that line out.

### Subprocess billed to the wrong account

`ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN` leaked into the unit
environment. The unit's `UnsetEnvironment=` line should prevent this — check
that it's present and the shell profile that invoked `systemctl --user` did
not re-export these variables.

## Other providers

<a id="other-providers"></a>

Cases specific to the non-CLI providers (`anthropic_http` / `openai_chat`).

### `HTTP 401` with `invalid x-api-key` or `invalid_api_key`

Wrong key slot. Providers store keys in the OS keychain under the preset's
`secret_slug` (see `src/hyacine/llm/providers.py`). For the desktop app,
re-run the provider step in the wizard and paste the key again; for a CLI
deploy, set `HYACINE_LLM_API_KEY` in `./.env`.

### `HTTP 403` / "region not supported" / "model not allowed"

Provider-side policy rejection. Check that `llm_model` in
`config/config.yaml` is a model the key has access to. Anthropic Console
keys only allow Claude models; a DeepSeek relay key won't authenticate
against `api.anthropic.com`, even though both speak the Claude wire
format.

### `output truncated` or `model refused`

`output truncated` means the reply hit its output budget: 16000 tokens for
the Anthropic Console (64000 at effort `xhigh` or `max`) and 4096 for relays
and OpenAI-compatible endpoints. Opus 5.5's thinking counts toward that
budget. Raise it with `HYACINE_LLM_MAX_TOKENS` in `./.env` (keep the
provider's own maximum in mind; DeepSeek rejects values above 8192), raise
`llm_timeout_seconds` to match, or lower `HYACINE_CLAUDE_EFFORT`.

If the error says `stop_reason=model_context_window_exceeded`, the *input*
filled the context window and a bigger output budget won't help: shrink the
window by moving the watermark forward (see `claude subprocess timed out`).

`model refused` is a safety-classifier decline (`stop_reason: refusal`); the
error names the category. On the Anthropic Console, Claude Opus 5 / 5.5,
Fable 5.1 and Sonnet 5.5 requests opt into the server-side fallback, so most
declines are retried on another model before you see this.

### `Connection refused` hitting a local Ollama / LM Studio

The local server isn't running or `llm_base_url` is wrong. Default for
Ollama is `http://localhost:11434`. Check with:

```bash
curl -s $(yq .llm_base_url config/config.yaml)/v1/models | head
```

If you're running Ollama in WSL but pointing from Windows (or vice
versa), the `localhost` loopback doesn't cross the WSL boundary —
bind the Ollama server on `0.0.0.0` and target the WSL IP instead.

### Output is in the wrong language

`config.yaml`'s `language` field (`en` / `zh-CN` / `zh-TW` / `ja`) is
appended to the user message as "Respond in …". If the model still
returns English, your prompt (in `prompts/hyacine.md`) probably has a
conflicting directive — the system prompt wins most of the time. Either
drop the English-only instruction from the prompt or tune the prompt
itself for the target locale.

## Desktop / wizard

### Graph wizard shows code + URL but the browser doesn't open

`@tauri-apps/plugin-opener` falls through to `xdg-open` on Linux. On
WSL this only works when `wslview` / `wslu` is installed and the
Windows-side default browser handler is registered. Workaround: copy
the URL (Copy button next to the code) into a browser manually —
the wizard is designed to surface the URL exactly for this case.

### `libEGL / MESA-LOADER: failed to retrieve device information` spam

Harmless WSLg warning from WebKit2GTK's GPU compositor looking for a
driver that doesn't exist inside WSL. If the window renders fine,
ignore it. If the window is black or flickering, disable GPU
compositing before launching:

```bash
export WEBKIT_DISABLE_COMPOSITING_MODE=1
export WEBKIT_DISABLE_DMABUF_RENDERER=1
npm run tauri:dev
```

### `tauri:dev` fails with "resource path `binaries/hyacine-ipc-…` doesn't exist"

The bundled sidecar binary hasn't been built. For a dev iteration
loop, generate it once with PyInstaller:

```bash
cd ~/hyacine
uv sync && uv pip install pyinstaller
cd desktop/sidecar
uv run pyinstaller hyacine-ipc.spec --distpath ../src-tauri/binaries --clean -y
mv ../src-tauri/binaries/hyacine-ipc \
   ../src-tauri/binaries/hyacine-ipc-$(rustc -vV | awk '/host/ {print $2}')
```

The Rust side falls back to `python3 -m hyacine.ipc` at *spawn time* if
the bundled binary errors, but the *build-time* `externalBin` check in
Tauri still requires the file to exist on disk.

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
it fires as soon as the user manager starts. A run that fails because the
network isn't up yet (or on any other transient error) is retried by the
unit's `Restart=on-failure` 15 minutes later. `Restart=` on a `Type=oneshot`
unit needs systemd 244 or newer.

Two limits apply to those retries:

- **At most 3 starts per 4 hours**, counting every start: timer, retry, or a
  manual `systemctl --user start`. Past that, systemd logs `Start request
  repeated too quickly` and refuses further starts. The web UI's "Run now"
  resets the counter first; from a shell, run
  `systemctl --user reset-failed hyacine-run.service`.
- **Exit status 3 is never retried.** The run exits 3 when `sendMail` failed
  in a way that doesn't rule out delivery (a read timeout, HTTP 500/502/504,
  or a SIGTERM mid-send), or when the digest was sent but the run couldn't be recorded. Retrying
  could mail a second digest, so check your inbox and start the run by hand
  if nothing arrived.

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
