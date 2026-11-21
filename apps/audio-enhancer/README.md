# Audio Enhancer

App de escritorio (Tauri + React + sidecar Python) para mejorar la calidad del audio.

```
apps/audio-enhancer/
├─ src/          Interfaz (React + TypeScript, textos en src/i18n/es.ts)
├─ src-tauri/    Shell Rust: ventana, supervisión del motor, empaquetado
└─ engine/       Motor de audio (Python, sidecar). Ver engine/README.md
```

## Desarrollo

```bash
# 1. Motor: dependencias, tests y binario congelado (necesario para tauri dev/build)
cd engine && uv sync && uv run pytest && uv run python scripts/build_sidecar.py && cd ..
# 2. Interfaz
pnpm install
pnpm tauri dev      # o: pnpm tauri build
```

Versiones: Python 3.12 (`engine/.python-version`, fijado), Node 22 y Rust `stable` (definidos en los workflows de CI; no hay `.nvmrc`). Los lockfiles (`uv.lock`, `pnpm-lock.yaml`, `Cargo.lock`) fijan las dependencias.
