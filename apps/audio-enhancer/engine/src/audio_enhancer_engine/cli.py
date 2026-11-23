"""CLI para ejercitar el motor sin interfaz: `audio-enhancer-cli enhance entrada salida [opciones]`."""

from __future__ import annotations

import argparse
import json
import sys

from . import ffmpeg_io, models, stages
from .denoise import IdentityDenoiser
from .models import ensure_deepfilternet3
from .pipeline import Cancelled, render, render_remux
from .settings import Settings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="audio-enhancer-cli", description="Mejora el audio de un archivo.")
    sub = p.add_subparsers(dest="command", required=True)

    probe = sub.add_parser("probe", help="Muestra las pistas de audio del archivo")
    probe.add_argument("input")

    enh = sub.add_parser("enhance", help="Mejora el audio")
    enh.add_argument("input")
    enh.add_argument("output", help="WAV/FLAC; con --remux, el video de salida (.mov, .mkv, .mp4)")
    enh.add_argument("--settings", help="JSON con ajustes (ver settings.py)")
    enh.add_argument("--region", nargs=2, type=float, metavar=("INICIO_S", "FIN_S"), help="Vista previa de una región")
    enh.add_argument("--audio-index", type=int, default=0, help="Pista de audio (0 = primera)")
    enh.add_argument("--remux", action="store_true", help="Reemplaza el audio del video sin recomprimirlo")
    enh.add_argument("--no-model", action="store_true", help="No usar IA (solo filtros y volumen)")
    args = p.parse_args(argv)

    try:
        if args.command == "probe":
            info = ffmpeg_io.probe(args.input)
            print(json.dumps(info.__dict__, default=lambda o: o.__dict__, ensure_ascii=False, indent=2))
            return 0

        settings = Settings.from_dict(json.loads(args.settings)) if args.settings else Settings()
        denoiser = None
        providers: list[str] = []
        if args.no_model:
            denoiser = IdentityDenoiser()
        else:
            ids = stages.needed_models(settings)
            if "deepfilternet3" in ids:
                ensure_deepfilternet3()
            reservation = models.use_models(ids)
            reservation.__enter__()
            denoiser = stages.build_chain(settings)
            providers = list(denoiser.providers) if denoiser else []

        def show(value: float, stage: str) -> None:
            print(f"\r{stage:<14}{value * 100:5.1f}%", end="", file=sys.stderr, flush=True)

        common = {"region": tuple(args.region) if args.region else None, "audio_index": args.audio_index,
                  "progress": show, "providers": providers}  # fmt: skip
        if args.remux:
            result = render_remux(args.input, args.output, settings, denoiser, **common)
        else:
            result = render(args.input, args.output, settings, denoiser, **common)
        print(file=sys.stderr)
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return 0
    except Cancelled:
        print("Cancelado.", file=sys.stderr)
        return 130
    except (ffmpeg_io.FfmpegError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
