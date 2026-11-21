"""Construye el sidecar con PyInstaller y lo coloca donde Tauri lo espera.

Tauri exige `src-tauri/binaries/<nombre>-<target-triple>[.exe]`.
Uso (desde engine/):  uv run python scripts/build_sidecar.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
BINARIES = ENGINE.parent / "src-tauri" / "binaries"
NAME = "audio-enhancer-engine"


def target_triple() -> str:
    out = subprocess.run(["rustc", "-vV"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"^host: (.+)$", out, re.MULTILINE)
    if not match:
        raise SystemExit("No se pudo determinar el target triple con `rustc -vV`.")
    return match.group(1).strip()


def main() -> None:
    triple = target_triple()
    exe = ".exe" if sys.platform == "win32" else ""
    subprocess.run(
        [
            sys.executable, "-m", "PyInstaller", "--onefile", "--clean", "--noconfirm",
            "--name", NAME,
            "--paths", str(ENGINE / "src"),
            "--collect-all", "onnxruntime",
            "--distpath", str(ENGINE / "dist"),
            "--workpath", str(ENGINE / "build"),
            "--specpath", str(ENGINE / "build"),
            str(ENGINE / "entry.py"),
        ],
        check=True,
        cwd=ENGINE,
    )
    BINARIES.mkdir(parents=True, exist_ok=True)
    dest = BINARIES / f"{NAME}-{triple}{exe}"
    shutil.copy2(ENGINE / "dist" / f"{NAME}{exe}", dest)
    print(f"Sidecar listo: {dest}")


if __name__ == "__main__":
    main()
