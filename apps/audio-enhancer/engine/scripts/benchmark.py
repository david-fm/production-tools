"""Benchmark del modelo: factor de tiempo real por proveedor y VRAM máxima (si hay nvidia-smi).

Uso:  uv run python scripts/benchmark.py [--minutes 5] [--audio ruta.wav]
Pensado para ejecutarse en la GTX 1650 Ti (Windows, DirectML). Pegar la salida en BENCHMARKS.md.

Criterios de aprobación (ver BENCHMARKS.md): VRAM máx. < 4096 MB y factor de tiempo real >= 1.0 en
el proveedor elegido (si DirectML es más lento que CPU o falla, se usa CPU).
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import threading
import time

import numpy as np
import onnxruntime as ort
import soundfile as sf

from audio_enhancer_engine.denoise import DeepFilterNet3
from audio_enhancer_engine.models import ensure_deepfilternet3
from audio_enhancer_engine.settings import SAMPLE_RATE


def vram_sampler(stop: threading.Event, peak: list[int]) -> None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return
    while not stop.is_set():
        out = subprocess.run(
            [exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, check=False
        )
        try:
            peak[0] = max(peak[0], int(out.stdout.strip().splitlines()[0]))
        except (ValueError, IndexError):
            pass
        time.sleep(0.2)


def load_audio(path: str | None, minutes: float) -> np.ndarray:
    if path:
        audio, sr = sf.read(path, dtype="float32", always_2d=True)
        if sr != SAMPLE_RATE:
            raise SystemExit(f"Se necesita audio a {SAMPLE_RATE} Hz (recibido {sr}).")
        return audio[: int(minutes * 60 * SAMPLE_RATE), 0]
    rng = np.random.default_rng(0)
    t = np.arange(int(minutes * 60 * SAMPLE_RATE)) / SAMPLE_RATE
    voice = 0.2 * np.sin(2 * np.pi * 180 * t) * (np.sin(2 * np.pi * 0.7 * t) > 0)
    return (voice + 0.03 * rng.standard_normal(len(t))).astype(np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=2.0)
    ap.add_argument("--audio")
    args = ap.parse_args()

    audio = load_audio(args.audio, args.minutes)
    block = audio[: 36 * SAMPLE_RATE]  # un bloque de producción (30 s + contexto)
    print(f"SO: {platform.platform()}  onnxruntime {ort.__version__}  proveedores: {ort.get_available_providers()}")
    folder = ensure_deepfilternet3()
    for providers in (["CPUExecutionProvider"], [p for p in ort.get_available_providers() if p != "CPUExecutionProvider"]):
        if not providers:
            continue
        try:
            model = DeepFilterNet3(folder, providers=providers + ["CPUExecutionProvider"])
        except Exception as exc:  # noqa: BLE001
            print(f"{providers}: no se pudo cargar ({exc})")
            continue
        stop, peak = threading.Event(), [0]
        th = threading.Thread(target=vram_sampler, args=(stop, peak), daemon=True)
        th.start()
        model.enhance(block[: 5 * SAMPLE_RATE])  # calentamiento
        t0 = time.perf_counter()
        model.enhance(block)
        dt = time.perf_counter() - t0
        stop.set()
        th.join()
        rtf = (len(block) / SAMPLE_RATE) / dt
        vram = f"{peak[0]} MB (usada en total, incluye el sistema)" if peak[0] else "n/d (sin nvidia-smi)"
        print(f"{model.providers}: bloque de {len(block)/SAMPLE_RATE:.0f} s en {dt:.2f} s -> x{rtf:.1f} tiempo real; VRAM: {vram}")
        print(f"   estimación: 1 h de audio mono en ~{3600 / rtf / 60:.1f} min")


if __name__ == "__main__":
    main()
