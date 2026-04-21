# App icons

Generate the required platform icons from `../../static/favicon.svg`:

```bash
cd desktop
npx @tauri-apps/cli icon static/favicon.svg
```

This writes:

- `icons/32x32.png`
- `icons/128x128.png`
- `icons/128x128@2x.png`
- `icons/icon.icns` (macOS)
- `icons/icon.ico` (Windows)

The files are gitignored because they're binary derivatives of the source SVG.
