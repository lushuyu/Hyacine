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
enough — if you hit this frequently, your fetch window is probably too large
(reduce `fetch_max_emails`).

### `claude returned an error`

Inspect the full error dict in the traceback. Common causes:

- **Daily usage cap hit** on your Claude Code subscription. Wait or upgrade.
- **Model name invalid**. Check `llm_model` in `config.yaml`.
- **Token revoked**. Regenerate with `claude setup-token`.

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
