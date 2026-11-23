"""Pipeline de mejora por bloques, determinista y reanudable.

Diseño (ver engine/README.md):
- El audio se decodifica UNA vez a un archivo float32 de 48 kHz (caché por huella del origen) y se
  lee por trozos con lecturas explícitas: la memoria no depende de la duración.
- El audio se procesa en bloques de rejilla GLOBAL (múltiplos de BLOCK_S desde el inicio). Cada bloque
  se calcula con contexto de calentamiento a ambos lados y se guarda en caché (`blocks/<hash>/k.npy`).
  Por eso la vista previa y el trabajo completo usan EXACTAMENTE los mismos bloques, y reanudar un
  trabajo es saltarse los bloques ya calculados. Cambiar ajustes u origen cambia el hash: la caché
  vieja no se reutiliza.
- Los bloques contiguos se unen con un crossfade lineal de 2*XFADE_S.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from . import ffmpeg_io
from .denoise import Chain, Denoiser
from .dsp import apply_filter, build_filter
from .loudness import LoudnessMeter
from .settings import SAMPLE_RATE, Settings

BLOCK_S = 30.0
XFADE_S = 0.05
CONTEXT_S = 3.0  # calentamiento de filtros y normalizadores del modelo (tau = 1 s)
MAX_CHANNELS = 8

B = int(BLOCK_S * SAMPLE_RATE)
X = int(XFADE_S * SAMPLE_RATE)
C = int(CONTEXT_S * SAMPLE_RATE)


class Cancelled(Exception):
    """El usuario canceló el trabajo."""


class InsufficientDisk(RuntimeError):
    """No hay espacio suficiente para los archivos temporales."""


ProgressFn = Callable[[float, str], None]


def _noop_progress(_value: float, _stage: str) -> None:
    return None


def fingerprint(path: str | os.PathLike[str]) -> str:
    """Huella del archivo de origen: tamaño + mtime + hash del primer MiB."""
    st = os.stat(path)
    h = hashlib.sha256(f"{st.st_size}:{st.st_mtime_ns}".encode())
    with open(path, "rb") as f:
        h.update(f.read(1 << 20))
    return h.hexdigest()[:16]


def read_f32(path: Path, start: int, stop: int, channels: int) -> np.ndarray:
    """Lee muestras [start, stop) de un f32 intercalado con lecturas explícitas.

    Se evita np.memmap a propósito: sus páginas cuentan como memoria residente del proceso y, en
    audios de horas, harían crecer el RSS con la duración.
    """
    with open(path, "rb") as f:
        f.seek(start * channels * 4)
        data = np.fromfile(f, dtype=np.float32, count=(stop - start) * channels)
    return data.reshape(-1, channels)


@dataclass
class Source:
    raw_path: Path
    n_samples: int
    channels: int
    key: str
    cache_dir: Path

    def read(self, start: int, stop: int) -> np.ndarray:
        """Muestras [start, stop) como (n, canales) float32, recortadas a los límites del archivo."""
        start, stop = max(0, start), min(self.n_samples, stop)
        if stop <= start:
            return np.zeros((0, self.channels), dtype=np.float32)
        return read_f32(self.raw_path, start, stop, self.channels)

    @property
    def meta_path(self) -> Path:
        return self.cache_dir / "meta.json"

    def _meta(self) -> dict[str, Any]:
        return json.loads(self.meta_path.read_text()) if self.meta_path.exists() else {}

    def original_lufs(self) -> float | None:
        meta = self._meta()
        if "lufs" not in meta:
            meter = LoudnessMeter(self.channels)
            for a in range(0, self.n_samples, 60 * SAMPLE_RATE):
                meter.add(self.read(a, a + 60 * SAMPLE_RATE))
            meta["lufs"] = meter.integrated()
            self.meta_path.write_text(json.dumps(meta))
        return meta["lufs"]


_source_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
CACHE_MAX_AGE_DAYS = float(os.environ.get("AUDIO_ENHANCER_CACHE_DAYS", "7"))


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _source_locks.setdefault(key, threading.Lock())


def purge_old_cache(work_root: Path, keep: Path | None = None, max_age_days: float = CACHE_MAX_AGE_DAYS) -> int:
    """Borra cachés de orígenes sin uso en `max_age_days`. Devuelve cuántas carpetas eliminó."""
    removed = 0
    cutoff = time.time() - max_age_days * 86400
    if not work_root.is_dir():
        return 0
    for entry in work_root.iterdir():
        try:
            if entry.is_dir() and entry != keep and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    return removed


def cache_size_bytes(work_root: Path | None = None) -> int:
    root = work_root or default_work_root()
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file()) if root.is_dir() else 0


def default_work_root() -> Path:
    override = os.environ.get("AUDIO_ENHANCER_WORK_DIR")
    return Path(override) if override else Path(tempfile.gettempdir()) / "audio-enhancer-work"


def prepare_source(
    src: str | os.PathLike[str],
    settings: Settings,
    *,
    work_root: Path | None = None,
    audio_index: int = 0,
    progress: ProgressFn = _noop_progress,
) -> Source:
    """Decodifica (o reutiliza la caché de) la pista de audio elegida."""
    info = ffmpeg_io.probe(src)
    if not info.audio_streams:
        raise ffmpeg_io.FfmpegError("El archivo no contiene ninguna pista de audio.")
    if not 0 <= audio_index < len(info.audio_streams):
        raise ffmpeg_io.FfmpegError(f"La pista de audio {audio_index} no existe (hay {len(info.audio_streams)}).")
    channels = 1 if settings.channels == "mix" else min(max(info.audio_streams[audio_index].channels, 1), MAX_CHANNELS)
    key = f"{fingerprint(src)}_a{audio_index}_c{channels}"
    root = work_root or default_work_root()
    cache_dir = root / key
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.utime(cache_dir)  # marca de uso reciente para la purga por antigüedad
    purge_old_cache(root, keep=cache_dir)
    raw, done = cache_dir / "source.f32", cache_dir / "source.done"

    with _lock_for(key):  # dos trabajos sobre el mismo origen no decodifican a la vez
        if not done.exists():
            if info.duration_s:  # estimación previa de espacio: fuente + bloques + temporal de salida
                needed = int(info.duration_s * SAMPLE_RATE * channels * 4 * 3)
                free = shutil.disk_usage(cache_dir).free
                if free < needed:
                    raise InsufficientDisk(
                        f"Se necesitan ~{needed / 1e9:.1f} GB libres para procesar y hay {free / 1e9:.1f} GB."
                    )
            progress(0.0, "decodificando")
            tmp = cache_dir / f"source.{uuid.uuid4().hex}.part"
            try:
                n = ffmpeg_io.decode_to_raw(src, tmp, audio_index=audio_index, channels=channels)
                if n == 0:
                    raise ffmpeg_io.FfmpegError("La pista de audio está vacía.")
                os.replace(tmp, raw)
            finally:
                tmp.unlink(missing_ok=True)
            done.write_text(str(n))
        n_samples = int(done.read_text())
    return Source(raw, n_samples, channels, key, cache_dir)


def _block_bounds(source: Source, k: int) -> tuple[int, int, int, int]:
    """(inicio_almacenado, fin_almacenado, inicio_ventana, fin_ventana) del bloque k, recortados al archivo."""
    s0, s1 = max(0, k * B - X), min(source.n_samples, (k + 1) * B + X)
    return s0, s1, max(0, s0 - C), min(source.n_samples, s1 + C)


def n_blocks(source: Source) -> int:
    return -(-source.n_samples // B)


def compute_block(source: Source, k: int, settings: Settings, denoiser: Denoiser | None, blocks_dir: Path) -> Path:
    """Calcula (o reutiliza) el bloque k. Escritura atómica: un corte nunca deja un bloque a medias."""
    path = blocks_dir / f"{k:06d}.npy"
    if path.exists():
        try:
            with path.open("rb") as f:  # sin mmap: en Windows un mapeo abierto impide reemplazar el archivo
                np.load(f)
            return path
        except (ValueError, OSError, EOFError):
            path.unlink(missing_ok=True)  # corrupto: se recalcula

    if settings.chain is not None:
        wants_stages = bool(settings.active_stages())
    else:
        wants_stages = (settings.denoise and settings.denoise_strength > 0) or settings.separate_model is not None
    if wants_stages and denoiser is None:
        raise ValueError("Los ajustes piden un modelo de audio pero no se proporcionó ninguno.")
    s0, s1, w0, w1 = _block_bounds(source, k)
    window = source.read(w0, w1)
    if isinstance(denoiser, Chain):
        # La cadena ya incluye los filtros y los modelos, en el orden pedido.
        out = np.stack([denoiser.enhance(window[:, c]) for c in range(window.shape[1])], axis=1).astype(np.float32)
    elif settings.chain is not None:
        out = window  # cadena explícita sin etapas activas: el audio pasa tal cual
    else:
        # Formato plano antiguo con un modelo suelto (tests y CLI): filtros y luego un solo denoiser.
        dry = apply_filter(build_filter(settings), window)
        out = dry
        if settings.denoise and denoiser is not None and settings.denoise_strength > 0:
            wet = np.stack([denoiser.enhance(dry[:, c]) for c in range(dry.shape[1])], axis=1)
            s = settings.denoise_strength
            out = (s * wet + (1.0 - s) * dry).astype(np.float32)
    result = np.ascontiguousarray(out[s0 - w0 : s1 - w0], dtype=np.float32)

    blocks_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{k:06d}.{uuid.uuid4().hex}.tmp.npy")  # único: dos procesos no se pisan
    np.save(tmp, result)
    try:
        os.replace(tmp, path)
    except PermissionError:
        # Windows: otro trabajo con los mismos ajustes está leyendo o acaba de escribir este bloque
        # (el contenido es idéntico: el directorio depende del hash de los ajustes).
        tmp.unlink(missing_ok=True)
        if not path.exists():
            raise
    return path


def _weighted_block(arr: np.ndarray, k: int, last: int, s0: int) -> np.ndarray:
    """Pesos de crossfade en coordenadas GLOBALES: entrada lineal sobre [kB-X, kB+X) y salida lineal sobre
    [(k+1)B-X, (k+1)B+X). En cada solape, peso_salida(k) + peso_entrada(k+1) == 1 exactamente."""
    pos = np.arange(s0, s0 + len(arr), dtype=np.float64)
    weight = np.ones(len(arr), dtype=np.float64)
    if k > 0:
        weight *= np.clip((pos - (k * B - X)) / (2 * X), 0.0, 1.0)
    if k < last:
        weight *= np.clip(((k + 1) * B + X - pos) / (2 * X), 0.0, 1.0)
    return (arr * weight[:, None]).astype(np.float32)


def assemble(
    source: Source, blocks_dir: Path, a: int, b: int, check_cancel: Callable[[], None] = lambda: None
) -> Iterator[np.ndarray]:
    """Genera el audio procesado de [a, b) en orden, uniendo bloques con crossfade. Memoria acotada."""
    a, b = max(0, a), min(source.n_samples, b)
    if b <= a:
        return
    last = n_blocks(source) - 1
    first_k, last_k = max(0, (a - X) // B), min(last, (b + X - 1) // B)
    pending_start = max(0, first_k * B - X)
    pending = np.zeros((0, source.channels), dtype=np.float32)

    for k in range(first_k, last_k + 1):
        check_cancel()
        s0 = max(0, k * B - X)
        arr = _weighted_block(np.load(blocks_dir / f"{k:06d}.npy"), k, last, s0)
        end = s0 + len(arr)
        if end > pending_start + len(pending):
            grow = end - pending_start - len(pending)
            pending = np.concatenate([pending, np.zeros((grow, source.channels), dtype=np.float32)])
        pending[s0 - pending_start : end - pending_start] += arr
        # Lo anterior al inicio del crossfade del bloque siguiente ya es definitivo.
        safe_end = end if k == last_k else (k + 1) * B - X
        n_emit = safe_end - pending_start
        if n_emit > 0:
            lo, hi = max(a, pending_start), min(b, pending_start + n_emit)
            if hi > lo:
                yield pending[lo - pending_start : hi - pending_start].copy()
            pending, pending_start = pending[n_emit:], pending_start + n_emit


@dataclass
class JobResult:
    output: str
    duration_s: float
    input_lufs: float | None
    output_lufs: float | None
    gain_db: float
    peak_limited: bool
    resumed_blocks: int
    providers: list[str]
    warnings: list[str]


def _check_paths(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
    """Valida ANTES de trabajar (un fallo tardío costaría horas): origen != destino."""
    same = Path(src).resolve() == Path(dst).resolve()
    if not same and Path(dst).exists():
        same = os.path.samefile(src, dst)
    if same:
        raise ValueError("El archivo de salida no puede ser el mismo que el de entrada.")


def _blocks_dir(source: Source, settings: Settings, denoiser: Denoiser | None = None) -> Path:
    fingerprints = getattr(denoiser, "fingerprints", None)
    return source.cache_dir / "blocks" / settings.processing_hash(fingerprints)


def render(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    settings: Settings,
    denoiser: Denoiser | None,
    *,
    region: tuple[float, float] | None = None,
    work_root: Path | None = None,
    audio_index: int = 0,
    progress: ProgressFn = _noop_progress,
    cancelled: Callable[[], bool] = lambda: False,
    providers: list[str] | None = None,
) -> JobResult:
    """Procesa `src` (o solo `region` en segundos, para vista previa) y escribe `dst`.

    - Trabajo completo (region=None): el volumen se mide sobre el resultado ya procesado y se ajusta
      al objetivo con exactitud (pasada extra).
    - Vista previa (region): el volumen usa la ganancia calculada sobre el audio ORIGINAL completo, igual
      que el trabajo completo antes de su pasada de ajuste fino; el resultado puede diferir ~1 LU.
    """
    settings.validate()
    warnings: list[str] = []
    _check_paths(src, dst)

    def check() -> None:
        if cancelled():
            raise Cancelled

    source = prepare_source(src, settings, work_root=work_root, audio_index=audio_index, progress=progress)
    check()
    if region is None:
        a, b = 0, source.n_samples
    else:
        a, b = int(region[0] * SAMPLE_RATE), int(region[1] * SAMPLE_RATE)
        if not 0 <= a < b <= source.n_samples:
            raise ValueError(f"La región {region} está fuera del audio (dura {source.n_samples / SAMPLE_RATE:.2f} s).")

    blocks_dir = _blocks_dir(source, settings, denoiser)
    first_k, last_k = max(0, (a - X) // B), min(n_blocks(source) - 1, (b + X - 1) // B)
    total = last_k - first_k + 1
    resumed = sum(1 for k in range(first_k, last_k + 1) if (blocks_dir / f"{k:06d}.npy").exists())
    for i, k in enumerate(range(first_k, last_k + 1)):
        check()
        progress(0.05 + 0.75 * i / total, "procesando")
        compute_block(source, k, settings, denoiser, blocks_dir)

    input_lufs = source.original_lufs() if settings.normalize else None
    fmt, subtype = ("WAV", "PCM_24") if settings.output_format == "wav24" else ("FLAC", "PCM_24")
    dst = Path(dst)

    out_lufs: float | None = None
    gain_db, limited = 0.0, False
    fd, tmp_name = tempfile.mkstemp(dir=source.cache_dir, prefix="assembled-", suffix=".f32")
    os.close(fd)
    tmp_path = Path(tmp_name)
    meter = LoudnessMeter(source.channels)
    peak = 0.0
    precise = settings.normalize and region is None

    wrote_dst = False
    try:
        progress(0.8, "uniendo")
        with open(tmp_path, "wb") as tmp:
            for chunk in assemble(source, blocks_dir, a, b, check):
                tmp.write(np.ascontiguousarray(chunk).tobytes())
                peak = max(peak, float(np.abs(chunk).max()))
                if precise:
                    meter.add(chunk)

        if settings.normalize:
            measured = meter.integrated() if precise else input_lufs
            if measured is None:
                reason = "dura menos de 0,4 s" if (b - a) < int(0.4 * SAMPLE_RATE) else "es demasiado silencioso"
                warnings.append(f"El audio {reason} para medir el volumen; no se normalizó.")
            else:
                gain_db = settings.target_lufs - measured
                peak_db = 20 * np.log10(peak) if peak > 0 else -200.0
                max_gain = settings.max_true_peak_db - peak_db
                if gain_db > max_gain:
                    gain_db, limited = max_gain, True
                    warnings.append("Se limitó el volumen para evitar saturación; no se alcanzó el objetivo.")
        gain = 10 ** (gain_db / 20)

        dst.parent.mkdir(parents=True, exist_ok=True)
        wrote_dst = True
        out_meter = LoudnessMeter(source.channels)
        n = b - a
        with sf.SoundFile(dst, "w", samplerate=SAMPLE_RATE, channels=source.channels, format=fmt, subtype=subtype) as out:
            step = 30 * SAMPLE_RATE
            for i in range(0, n, step):
                check()
                piece = np.clip(read_f32(tmp_path, i, min(n, i + step), source.channels) * gain, -1.0, 1.0)
                out.write(piece)
                out_meter.add(piece)
                progress(0.85 + 0.15 * min(1.0, (i + step) / n), "escribiendo")
        out_lufs = out_meter.integrated()
    except BaseException:
        if wrote_dst:
            dst.unlink(missing_ok=True)  # nunca se deja un archivo de salida a medias
        raise
    finally:
        tmp_path.unlink(missing_ok=True)
    progress(1.0, "listo")
    return JobResult(
        output=os.fspath(dst), duration_s=n / SAMPLE_RATE, input_lufs=input_lufs, output_lufs=out_lufs,
        gain_db=float(gain_db), peak_limited=limited, resumed_blocks=resumed,
        providers=providers or [], warnings=warnings,
    )  # fmt: skip


def clear_cache(work_root: Path | None = None) -> None:
    shutil.rmtree(work_root or default_work_root(), ignore_errors=True)


def extract_original(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    region: tuple[float, float],
    *,
    work_root: Path | None = None,
    audio_index: int = 0,
    channels: str = "each",
) -> dict[str, Any]:
    """Escribe la región ORIGINAL (sin procesar) para la comparación A/B, y devuelve su loudness."""
    source = prepare_source(src, Settings(channels=channels), work_root=work_root, audio_index=audio_index)
    a, b = int(region[0] * SAMPLE_RATE), int(region[1] * SAMPLE_RATE)
    if not 0 <= a < b <= source.n_samples:
        raise ValueError(f"La región {region} está fuera del audio (dura {source.n_samples / SAMPLE_RATE:.2f} s).")
    audio = source.read(a, b)
    meter = LoudnessMeter(source.channels)
    meter.add(audio)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    sf.write(dst, audio, SAMPLE_RATE, subtype="PCM_24", format="WAV")
    return {"output": os.fspath(dst), "duration_s": (b - a) / SAMPLE_RATE, "lufs": meter.integrated()}


def waveform_peaks(
    src: str | os.PathLike[str],
    points: int,
    *,
    work_root: Path | None = None,
    audio_index: int = 0,
    channels: str = "each",
) -> dict[str, Any]:
    """Picos (mín/máx por columna) para dibujar la forma de onda, sobre la mezcla a mono. Memoria acotada."""
    source = prepare_source(src, Settings(channels=channels), work_root=work_root, audio_index=audio_index)
    points = max(1, min(points, 20_000))
    edges = np.linspace(0, source.n_samples, points + 1).astype(np.int64)
    mins, maxs = np.zeros(points, dtype=np.float32), np.zeros(points, dtype=np.float32)
    step = 10 * SAMPLE_RATE
    for i in range(points):
        lo, hi = int(edges[i]), int(edges[i + 1])
        peak_lo, peak_hi = 0.0, 0.0
        for a in range(lo, hi, step):
            chunk = source.read(a, min(hi, a + step)).mean(axis=1)
            if len(chunk):
                peak_lo, peak_hi = min(peak_lo, float(chunk.min())), max(peak_hi, float(chunk.max()))
        mins[i], maxs[i] = peak_lo, peak_hi
    return {
        "duration_s": source.n_samples / SAMPLE_RATE,
        "channels": source.channels,
        "min": mins.round(4).tolist(),
        "max": maxs.round(4).tolist(),
    }


def render_remux(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    settings: Settings,
    denoiser: Denoiser | None,
    **kwargs: Any,
) -> JobResult:
    """Procesa el audio de `src` y lo une al video original (sin recomprimirlo) en `dst`.

    Valida extensión y rutas ANTES de procesar y deja el WAV intermedio en el directorio de trabajo
    (nunca junto al video del usuario), borrándolo siempre.
    """
    if Path(dst).suffix.lower() not in ffmpeg_io.REMUX_EXTENSIONS:
        raise ValueError(f"Para guardar video usa una de estas extensiones: {', '.join(ffmpeg_io.REMUX_EXTENSIONS)}")
    _check_paths(src, dst)
    root = kwargs.get("work_root") or default_work_root()
    root.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=root, prefix="remux-", suffix=".wav")
    os.close(fd)
    audio = Path(name)
    try:
        result = render(src, audio, settings, denoiser, **kwargs)
        ffmpeg_io.remux(src, audio, dst)
        result.output = os.fspath(dst)
        return result
    except BaseException:
        # Un video de salida a medias no sirve; el origen nunca se toca (ya se validó dst != src).
        Path(dst).unlink(missing_ok=True)
        raise
    finally:
        audio.unlink(missing_ok=True)
