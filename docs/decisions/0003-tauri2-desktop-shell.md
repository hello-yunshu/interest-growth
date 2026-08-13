# ADR 0003 — Tauri 2 desktop shell

## Decision
Use Tauri 2 as the Windows/macOS desktop shell, static Next.js/React as the UI, and a PyInstaller-packaged Psychology Growth Python Core as an owned sidecar.

## Why
This preserves the existing Python domain instead of introducing a Go/Node business bridge; avoids bundling a full Chromium runtime; gives explicit Tauri capabilities, native window state/effects, sidecar lifecycle, installers and signed-updater infrastructure.

## Rejected for v0.4
- Electron: mature but materially heavier for this local-first product.
- Wails v3: attractive but would introduce a Go bridge and was still pre-release during the architecture review.
- Electrobun: promising but too young for the long-lived private-data desktop core.

The choice does not make Tauri part of the product domain. The UI and Python core remain separable from the shell.
