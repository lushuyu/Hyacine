# Changelog

All notable changes to Hyacine are listed here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Claude Opus 5.5 becomes the default model, plus a sweep of fixes for
problems that quietly degraded the daily digest: calendar times shifted by
the UTC offset, a calendar capped at 10 events, Sent Items and the previous
digest fed back to the model, no retries on transient Graph errors, starter
rules that never loaded, and failure alerts that were configured but never
sent.

### Added

- **`interactive_browser` Graph sign-in.** `HYACINE_GRAPH_AUTH_MODE=interactive_browser`
  uses the authorization-code + PKCE flow on a loopback port
  (`HYACINE_GRAPH_REDIRECT_PORT`, default 8400), for tenants whose Conditional
  Access blocks device code (`AADSTS530036`). `scripts/bootstrap_auth.py` gains
  `--check` (verify without prompting) and `--reset`, and reports success only
  once the cached refresh token is actually redeemed, not merely when a
  cached access token answers. The scheduled run never starts an interactive
  login: a dead refresh token fails the run at once.

### Changed

- **Default model is `claude-opus-5-5`.** One constant,
  `hyacine.llm.providers.DEFAULT_CLAUDE_MODEL`, now feeds the CLI and
  Anthropic Console presets, `YamlConfig.llm_model`, the wizard, the probe
  fallbacks and the desktop mirrors. The desktop Settings model picker lists
  the active provider's models and always keeps the saved one. Existing
  installs keep whatever `llm_model` their `config.yaml` pins.
- **`claude -p` runs isolated.** The CLI provider sets
  `CLAUDE_CODE_SAFE_MODE=1`, so your `~/.claude` customizations (CLAUDE.md,
  hooks, plugins, MCP servers) no longer load into the daily run. It pins
  `CLAUDE_CODE_EFFORT_LEVEL` from `HYACINE_CLAUDE_EFFORT` (default `high`)
  and runs from an empty temp directory. Set `HYACINE_CLAUDE_SAFE_MODE=0` to
  opt out.
- **Leaner LLM payload.** Graph message ids and the duplicated sender domain
  are no longer sent to the model, and calendar attendee lists are capped at
  10.
- **`fetch_max_emails` is enforced.** Each run hands the LLM the newest
  `fetch_max_emails` emails (default 500). When older mail is left out, the
  journal logs a warning and the digest is told to say so at the top.
- **Desktop data lives in the per-user app data dir** instead of the OS temp
  dir, for config, the run database and the Graph sign-in alike. Existing
  desktop users set up once more after upgrading.
- **The run unit retries failed runs.** `hyacine-run.service` gains
  `Restart=on-failure` (15 min apart; 3 starts of any kind per 4 h) and a
  40-minute start timeout. It needs systemd 244 or newer. Installed copies
  must be updated by hand.
- **Exit status 3 means "don't retry".** A run exits 3 when `sendMail` failed
  in a way that doesn't rule out delivery (a read timeout, HTTP 500/502/504,
  or a SIGTERM mid-send), or when the digest went out but the run
  couldn't be recorded. The unit sets `RestartPreventExitStatus=3`, so those
  runs aren't retried into a second digest.
  A run stopped by SIGTERM (e.g. the start timeout) now marks itself failed
  and alerts instead of staying "running".
- **Configurable output budget for HTTP providers.** `HYACINE_LLM_MAX_TOKENS`
  overrides the defaults: 16000 for the Anthropic Console (64000 at effort
  `xhigh` or `max`), 4096 for relays and OpenAI-compatible endpoints.

### Fixed

- **Calendar times.** Events were serialized as UTC while holding local
  wall-clock times, so they were off by the UTC offset. They now carry the
  configured zone (`+08:00` for Asia/Singapore). The calendar window is the
  local day, not the UTC day, and `calendarView` is paginated past Graph's
  default of 10 events.
- **Mail outside the inbox.** Sent Items, Drafts, Deleted Items, Junk and
  Outbox are skipped, and so is Hyacine's own digest.
- **Transient Graph errors.** Graph calls retry on 429 and 5xx and honour
  `Retry-After`. `sendMail` retries only when the request provably never
  reached Graph, so it can't send a duplicate digest. Errors now include
  Graph's error body.
- **Opus 5.5 over the Messages API.** First-party requests get room for
  always-on thinking (`max_tokens` 16000) and an explicit effort level.
  Current models also get the server-side refusal fallback. Refusals,
  truncated output and empty replies raise clear errors instead of being
  mailed as the digest. The OpenAI-compatible backend checks
  `finish_reason`.
- **Starter rules.** `config/rules.starter.yaml` used categories missing from
  `CategoryHint`, so it never loaded and classification was silently off.
  The categories now exist, and an empty matcher matches nothing instead of
  everything. Rules that were too broad to switch on are narrowed: a
  `noreply@` sender no longer means marketing, "offer"/"deal" no longer mean
  promo, and calendar responses must start with `Accepted:`, `Declined:` and
  the like. Invalid `subject_regex` patterns are rejected when rules are
  saved instead of crashing the run. A rules file that fails to load now
  logs a warning.

  **Upgrade note:** an existing `config/rules.yaml` copied from the old
  starter starts loading with this release, including the over-broad rules.
  If yours is an unmodified copy, replace it with the new
  `config/rules.starter.yaml`; otherwise apply the same edits by hand.
- **Failure alerts.** `HYACINE_NTFY_TOPIC` alerts now fire when a systemd or
  CLI run fails. Each carries a one-line summary of the final exception (the
  whole message, not just its last line, capped at 200 characters), and a
  crash prints its traceback to the journal.
- **"Run now" started two pipelines.** It now uses
  `systemctl start --no-block` and never falls back to a second
  unsupervised run on timeout. It also resets the unit's start limit first,
  so a deliberate manual run is never silently refused.
- **Cross-site writes to the web UI.** State-changing requests from other
  origins get a 403. Setting `HYACINE_WEB_ALLOWED_HOSTS` additionally pins
  accepted Host names; entries may include a port or be pasted as URLs.
- **`claude -p` robustness.** A relative `HYACINE_CLAUDE_BIN` keeps working
  from the temp working directory, a missing binary raises a clear error, and
  an empty result fails the run instead of mailing an empty digest. The
  wizard's provider test uses the same isolated environment as the real run.
- **Remote images in the digest.** `<img>` is no longer allowed by the
  sanitizer.
- Wizard backups such as `.env.bak-*`, which hold the OAuth token, are now
  gitignored.
- **`hyacine init` → update** backs up every file it rewrites (chmod 600) and
  keeps config keys the wizard doesn't ask about, including `llm_model` and
  the provider settings. Current values, the Graph tenant included, are the
  prompt defaults.
- **`doctor.py`** checks the `./.env` values the systemd timer actually uses
  (and flags a different or placeholder shell export), checks
  `HYACINE_LLM_API_KEY` for HTTP providers, honours `HYACINE_AUTH_RECORD_PATH`,
  and validates `config.yaml` and `rules.yaml` against the schemas the
  pipeline uses instead of only parsing the YAML.
- **`scripts/test_sendmail.py`** uses the configured Graph auth mode and never
  starts an interactive login; a dead sign-in fails before the send prompt.
- **Desktop sidecar.** It starts on demand, restarts after a crash, and
  restarts after a key save or provider switch so new keys take effect without
  relaunching. Pipeline runs no longer hit the 60 s RPC timeout. Its stdio is
  UTF-8 on Windows, and `tzdata` ships for Windows' missing zone database.
  Config edits apply without an app restart.
- **Desktop keys.** Testing a provider uses only that provider's own stored
  key, and only at the endpoint it was saved for (a changed custom base URL
  needs the key re-entered); never the active provider's. Re-entering the wizard keeps the saved
  config, and "Rotate / switch" or "Replace" no longer deletes the stored key
  before a new one is saved.
- **Desktop wizard.** The Graph step's "Open browser" works again (the opener
  capability had no URL scope), and the device sign-in can be restarted
  right after a cancel. Unused webview permissions are dropped. "Run now"
  reports failed runs with their error instead of showing success, and warns
  to check the inbox before re-running when the send outcome is unknown. `config.write` rejects
  invalid values and unknown timezones, and config, prompt and rules writes
  are atomic.

## [1.2.0] — 2026-04-26

Email pipeline cut: the daily digest gets HyacineAI's design language
(pansy header, hero serif title, color-bar section titles, three-segment
footer with provider/model) across Apple Mail, Gmail web, iOS Mail, and
Outlook 2016+. Plus security + correctness hardening on the renderer
(escape config-derived strings before interpolating into HTML, harden
the anchor regex against quoted `>`, drop dead exception-swallowing
fallback in the run-detail view), end-to-end language plumbing
(`<html lang>` reflects the configured language with a sensible
fallback), a new public `hyacine.i18n` module, and dry-run preview
parity with real sends.

### Added

- **Modern HTML email shell.** New `hyacine.graph.email_render` module
  wraps the LLM markdown in HyacineAI's design language — header carries
  date + localised weekday, section titles take their color bar from the
  prompt template's emoji prefixes (🔴/🟡/🟢/⚪), footer surfaces the
  active provider/model. All inline styles, no external assets.
- **`hyacine.i18n` module.** New public `weekday_label(dt, language)`
  helper supporting `en`, `zh-CN`, `zh-TW`, `ja` (English fallback for
  unknown codes); previously a private helper inside `pipeline.run`.
- **`render_html_fragment` API.** Same sanitisation + design language
  as `render_html_body` but skips the `<html>` shell so the FastAPI
  run-detail view embeds without nesting documents inside a `<div>`.
- **Per-language `<html lang>` attribute.** `render_modern_email_html`
  accepts a `language` argument and maps YAML config codes to BCP-47
  tags so screen readers / client heuristics see the language the
  digest was actually written in.

### Fixed

- **Run-detail view nested a full HTML document inside a `<div>`.**
  Switched the markdown renderer to `render_html_fragment` so the
  embedded body is now a clean fragment.
- **Dry-run wizard preview footer drifted from the real send.** Preview
  now reads `language` and `timezone` from the YAML config and computes
  `now` in that zone, going through the same `weekday_label` helper as
  the pipeline. Run-time values (date / time / weekday) inherently
  shift between preview and run; everything else now matches.
- **Anchor styling regex terminated early on `>` inside quoted attrs.**
  Pattern now treats quoted strings atomically so e.g. `title="a>b"`
  no longer breaks link styling.
- **Dead `NotImplementedError` fallback in `web/routes/runs.py`.**
  `render_html_fragment` never raises it; the catch was masking
  unrelated runtime errors. Restricted to module-import-only.
- **Unknown language codes leaked into `<html lang>`.** `_bcp47` now
  defaults to `en` when the config language isn't one we localise,
  matching the docstring contract.

### Changed

- Pipeline forwards `model`, local `date` / `weekday` / `time`, and
  `language` into `send_email` so the modern footer reflects the
  per-run config.
- Version bumped to 1.2.0 across `pyproject.toml`, `desktop/package.json`,
  `desktop/package-lock.json`, `desktop/src-tauri/tauri.conf.json`,
  `desktop/src-tauri/Cargo.toml`, and `desktop/src-tauri/Cargo.lock`.

## [1.1.0] — 2026-04-23

Release-engineering cut that makes the desktop wizard end-to-end usable,
stops dry-run from actually sending email, and splits CI so stable /
pre-release / nightly each behave correctly on the GitHub Releases page.

### Added

- **Language honoured by the LLM.** `config.yaml`'s `language` is now
  appended to the user message sent to the model, so `zh-CN` actually
  produces Chinese output instead of silently defaulting to English.
- **Provider-aware UI.** `i18n` gained a `{provider}` placeholder and a
  `providerName` store populated from `providers.current`. Wizard stage
  labels ("Invoke {provider}"), connectivity cards ("{provider} API"),
  identity hints, and settings all read the active provider instead of
  hard-coding "Claude".
- **Connectivity check targets the active provider.** `rust_probe_claude`
  now routes through `providers.test` with the current provider's
  metadata (api_format, base_url, key-slug) instead of always pinging
  `api.anthropic.com` with the legacy `"claude"` keychain slot.
- **CI release channels.**
  - `refs/tags/vX.Y.Z` (pure semver) → stable, promoted to "Latest".
  - `refs/tags/vX.Y.Z-rc1` / `-beta` / `+build` → pre-release, not Latest.
  - `refs/heads/main` → nightly, not Latest (unchanged).

### Fixed

- **Graph device-code wizard sat on a spinner forever** because
  `graph.me` silently triggered a fresh device flow on cache expiry,
  blocking the dispatch thread and corrupting the JSON-RPC channel with
  MSAL's verification print. Switched the existing-record paths to
  silent-refresh-only (`disable_automatic_auth=True`) and wired the
  emit-based prompt callback through `build_credential` rather than a
  post-hoc attribute assignment.
- **Tauri 2 `listen` rejected `.` in event names.** Every subscription to
  `rpc:graph.device_flow` / `rpc:pipeline.progress` threw
  `invalid args event for command listen`. The sidecar bridge now
  translates `.` → `/`; listeners subscribe to the slashed form.
- **Dry run actually sent email.** `run_pipeline()` had no dry-run flag.
  Added `dry_run=True`; the preview path now skips `sendMail` and leaves
  the watermark untouched.
- **Preview progress was synthetic** — all five stages ticked to `ok`
  at once. `run_pipeline()` gained a `progress` callback plumbed through
  real stage boundaries (fetch / classify / llm / render / deliver).
- **`YamlConfig` rejected wizard fields.** `identity` and `priorities`
  are wizard-owned and read from the raw YAML; they now pass the model
  validator via `extra="ignore"`.
- **PyInstaller missed `hyacine` under editable installs.** `pathex`
  points at `../../src` so modulegraph resolves the `.pth` shim
  consistently.
- **WSL / headless device-code UX.** The Graph wizard now shows the
  verification URL as a copy-able string next to the code and hints at
  manual-browser fallback — `openUrl` failures surface as a toast
  instead of silent spinning.

### Changed

- Version bumped to 1.1.0 across `pyproject.toml`, `desktop/package.json`,
  `desktop/src-tauri/tauri.conf.json`, and `desktop/src-tauri/Cargo.toml`.

## [1.0.0] — 2026-04-??

Initial public release. Multi-provider LLM support, first-run wizard,
Tauri + SvelteKit desktop shell, systemd deploy path, Microsoft Graph
OAuth with persistent cache.

### Added

- **Pipeline.** Outlook inbox + calendar via Microsoft Graph → rules
  classifier → LLM → HTML email delivered via `/me/sendMail`, with a
  watermark-gated fetch window in SQLite.
- **Multi-provider LLM.** Registry of built-in presets covering Claude
  Code OAuth (`anthropic_cli`), Anthropic Console, DeepSeek, Kimi,
  Zhipu GLM (`anthropic_http`), OpenAI, Groq, Ollama (`openai_chat`),
  plus a "Custom" picker for arbitrary endpoints.
- **Web UI.** FastAPI + Jinja views for run history, per-run snapshots,
  prompt editor, and rules editor.
- **Desktop app.** Tauri 2 + SvelteKit + Tailwind wizard/dashboard with
  OS-keychain secret storage, JSON-RPC Python sidecar, and connectivity
  probes.
- **CI.** Cross-platform installer matrix (macOS, Windows x64/arm64,
  Linux x64/arm64) with PyInstaller-bundled sidecar and automated
  GitHub Releases.
