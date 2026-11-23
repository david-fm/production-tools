#!/usr/bin/env bash
# Captura SOLO la ventana de Audio Enhancer en macOS (no la pantalla completa, para no incluir otras apps).
# Uso: scripts/capture-window.sh salida.png [nombre-del-propietario]
set -euo pipefail
out="${1:?uso: capture-window.sh salida.png [propietario]}"
owner="${2:-Audio Enhancer}"
tmp="$(mktemp -d)"
cat > "$tmp/winid.swift" <<'SWIFT'
import CoreGraphics
let owner = CommandLine.arguments[1]
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as! [[String: Any]]
for w in list where (w[kCGWindowOwnerName as String] as? String) == owner {
    let b = w[kCGWindowBounds as String] as? [String: Any]
    if (b?["Height"] as? Double ?? 0) > 100 { print(w[kCGWindowNumber as String] ?? ""); break }
}
SWIFT
id="$(swift "$tmp/winid.swift" "$owner")"
rm -rf "$tmp"
[ -n "$id" ] || { echo "No se encontró la ventana de «$owner» (¿está abierta y visible?)" >&2; exit 1; }
screencapture -x -o -l "$id" "$out"
echo "$out"
