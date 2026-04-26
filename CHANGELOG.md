# Changelog

All notable changes to Hyacine are listed here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
