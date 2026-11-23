"""Bucle del protocolo JSON-por-línea sobre stdio.

Contrato completo en engine/README.md. Reglas clave:
- stdin: una petición JSON por línea. stdout: SOLO mensajes JSON, una línea cada uno.
- Logs y diagnósticos van a stderr, nunca a stdout.
- Si stdin se cierra (la app murió o se cerró), el motor termina: evita procesos huérfanos.
- El hilo lector nunca ejecuta trabajo lento: `ping`, `cancel` y `shutdown` siempre responden,
  aunque haya tareas largas o una importación pesada (onnxruntime) en curso.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections.abc import Callable
from typing import IO, Any

from . import __version__

_write_lock = threading.Lock()


def send(out: IO[str], message: dict[str, Any]) -> None:
    """Escribe un mensaje por línea; el lock evita que hilos mezclen líneas."""
    with _write_lock:
        out.write(json.dumps(message, ensure_ascii=False) + "\n")
        out.flush()


def available_providers() -> list[str]:
    """Proveedores de ONNX Runtime disponibles en ESTE binario (probado también congelado)."""
    import onnxruntime

    return list(onnxruntime.get_available_providers())


class Tasks:
    """Tareas en segundo plano, cada una con su propio token de cancelación (por id)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[Any, threading.Event] = {}
        self._threads: list[threading.Thread] = []

    def start(
        self, req_id: Any, work: Callable[[threading.Event], None], out: IO[str], key: Any = None
    ) -> None:
        """Arranca `work` en un hilo. `key` (por defecto el id de la petición) identifica la tarea para
        `cancel` y evita dos tareas simultáneas con la misma clave."""
        key = req_id if key is None else key
        # El token se registra en el hilo lector, ANTES de arrancar el hilo: un `cancel`
        # que llegue justo después ya lo encuentra.
        token = threading.Event()
        with self._lock:
            if key in self._tokens:
                send(out, {"id": req_id, "ok": False, "error": f"ya hay una tarea {key!r} en curso"})
                return
            self._tokens[key] = token
            self._threads = [t for t in self._threads if t.is_alive()]  # no acumular hilos terminados

        def runner() -> None:
            try:
                work(token)
            except Exception as exc:  # noqa: BLE001 - toda tarea debe responder, también al fallar
                send(out, {"id": req_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
            finally:
                with self._lock:
                    self._tokens.pop(key, None)

        thread = threading.Thread(target=runner, daemon=True)
        with self._lock:
            self._threads.append(thread)
        thread.start()

    def cancel(self, target: Any | None) -> int:
        """Cancela la tarea `target`, o todas si es None. Devuelve cuántas señaló."""
        with self._lock:
            tokens = [t for k, t in self._tokens.items() if target is None or k == target]
        for token in tokens:
            token.set()
        return len(tokens)

    def shutdown(self, timeout: float = 2.0) -> None:
        self.cancel(None)
        deadline = time.monotonic() + timeout
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))


def _number(request: dict[str, Any], key: str, default: float, lo: float, hi: float) -> float:
    value = request.get(key, default)
    is_number = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not is_number or not lo <= value <= hi:
        raise ValueError(f"'{key}' debe ser un número entre {lo} y {hi}")
    return float(value)


def _progress_demo(request: dict[str, Any], out: IO[str]) -> Callable[[threading.Event], None]:
    req_id = request.get("id")
    steps = int(_number(request, "steps", 5, 1, 100_000))
    delay = _number(request, "delay", 0.05, 0, 10)

    def work(token: threading.Event) -> None:
        for i in range(1, steps + 1):
            if token.is_set():
                send(out, {"id": req_id, "ok": False, "error": "cancelado"})
                return
            send(out, {"event": "progress", "id": req_id, "value": i / steps})
            time.sleep(delay)
        send(out, {"id": req_id, "ok": True, "result": "listo"})

    return work


def _providers(request: dict[str, Any], out: IO[str]) -> Callable[[threading.Event], None]:
    req_id = request.get("id")

    def work(_token: threading.Event) -> None:
        try:
            send(out, {"id": req_id, "ok": True, "result": available_providers()})
        except ImportError as exc:
            send(out, {"id": req_id, "ok": False, "error": f"onnxruntime no disponible: {exc}"})

    return work


def _job(
    request: dict[str, Any], out: IO[str], fn: Callable[[Callable[[float, str], None], Callable[[], bool]], Any]
) -> Callable[[threading.Event], None]:
    """Envuelve un trabajo largo: emite progreso, responde con el resultado y traduce errores a mensajes legibles."""
    req_id = request.get("id")

    def work(token: threading.Event) -> None:
        from .ffmpeg_io import FfmpegError
        from .models import ModelError
        from .pipeline import Cancelled, InsufficientDisk

        def progress(value: float, stage: str) -> None:
            send(out, {"event": "progress", "id": req_id, "job": request.get("job"),
                       "value": round(value, 4), "stage": stage})  # fmt: skip

        try:
            send(out, {"id": req_id, "ok": True, "result": fn(progress, token.is_set)})
        except Cancelled:
            send(out, {"id": req_id, "ok": False, "error": "cancelado"})
        except (FfmpegError, InsufficientDisk, ModelError, ValueError, OSError) as exc:
            send(out, {"id": req_id, "ok": False, "error": str(exc)})

    return work


def _job_key(request: dict[str, Any]) -> Any:
    job = request.get("job")
    if job is not None and not isinstance(job, (str, int)):
        raise ValueError("'job' debe ser texto o número")
    return job


def _require_str(request: dict[str, Any], key: str) -> str:
    value = request.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"'{key}' es obligatorio y debe ser texto")
    return value


def _region(request: dict[str, Any]) -> tuple[float, float] | None:
    region = request.get("region")
    if region is None:
        return None
    if not (isinstance(region, list) and len(region) == 2 and all(isinstance(v, (int, float)) for v in region)):
        raise ValueError("'region' debe ser [inicio_s, fin_s]")
    return float(region[0]), float(region[1])


def _audio_index(request: dict[str, Any]) -> int:
    value = request.get("audio_index", 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("'audio_index' debe ser un entero >= 0")
    return value


def _enhance(request: dict[str, Any], out: IO[str]) -> Callable[[threading.Event], None]:
    from .pipeline import render
    from .settings import Settings

    src, dst = _require_str(request, "input"), _require_str(request, "output")
    settings = Settings.from_dict(request.get("settings") or {})
    region, audio_index = _region(request), _audio_index(request)
    remux = bool(request.get("remux", False))

    def run(progress: Callable[[float, str], None], cancelled: Callable[[], bool]) -> dict[str, Any]:
        from . import models, stages
        from .pipeline import render_remux

        ids = stages.needed_models(settings)
        if "deepfilternet3" in ids:  # comportamiento de v0.1.0: se descarga solo si falta
            models.install("deepfilternet3", progress=progress, cancelled=cancelled)
        with models.use_models(ids):  # los modelos no se pueden quitar mientras dura el trabajo
            chain = stages.build_chain(settings)
            kwargs: dict[str, Any] = {
                "region": region, "audio_index": audio_index, "progress": progress, "cancelled": cancelled,
                "providers": list(chain.providers) if chain else [],
            }  # fmt: skip
            if remux:
                return render_remux(src, dst, settings, chain, **kwargs).__dict__
            return render(src, dst, settings, chain, **kwargs).__dict__

    return _job(request, out, run)


def _simple(request: dict[str, Any], out: IO[str], fn: Callable[[dict[str, Any]], Any]) -> Callable[[threading.Event], None]:
    return _job(request, out, lambda _p, _c: fn(request))


def _cmd_probe(request: dict[str, Any]) -> Any:
    from .ffmpeg_io import probe

    info = probe(_require_str(request, "path"))
    return {
        "duration_s": info.duration_s,
        "has_video": info.has_video,
        "audio_streams": [s.__dict__ for s in info.audio_streams],
    }


def _cmd_waveform(request: dict[str, Any]) -> Any:
    from .pipeline import waveform_peaks

    return waveform_peaks(_require_str(request, "path"), int(request.get("points", 1200)),
                          audio_index=int(request.get("audio_index", 0)),
                          channels=str(request.get("channels", "each")))  # fmt: skip


def _cmd_extract(request: dict[str, Any]) -> Any:
    from .pipeline import extract_original

    region = _region(request)
    if region is None:
        raise ValueError("'region' es obligatorio")
    return extract_original(_require_str(request, "input"), _require_str(request, "output"), region,
                            audio_index=int(request.get("audio_index", 0)),
                            channels=str(request.get("channels", "each")))  # fmt: skip


def _cmd_preferred_providers(_request: dict[str, Any]) -> Any:
    from .denoise import preferred_providers

    return preferred_providers()


def _cmd_models_status(_request: dict[str, Any]) -> Any:
    """Compatible con v0.1.0: {deepfilternet3: {installed, path}} (App.test.tsx lo usa)."""
    from . import models

    e = models.CATALOG["deepfilternet3"]
    return {"deepfilternet3": {"installed": models.entry_status(e) == "installed",
                               "path": str(models.model_folder("deepfilternet3"))}}  # fmt: skip


FILTER_INFO = [
    {"kind": "highpass", "name": "Recorte de graves", "description": "Quita retumbos y viento por debajo de una frecuencia."},
    {"kind": "notch", "name": "Zumbido eléctrico", "description": "Elimina el zumbido de la red eléctrica y sus armónicos."},
]


def _cmd_stage_catalog(_request: dict[str, Any]) -> Any:
    """Cajas que se pueden añadir a la cadena: filtros (con su esquema) y modelos del catálogo."""
    from . import models
    from .schema import params_schema

    return {
        "filters": [{**f, "params": params_schema(f["kind"])} for f in FILTER_INFO],
        "models": [m for m in models.list_models() if m["task"] in ("denoise", "separate", "unknown")],
    }


def _cmd_models_catalog(_request: dict[str, Any]) -> Any:
    from . import models

    return models.list_models()


def _cmd_cache_info(_request: dict[str, Any]) -> Any:
    from .pipeline import cache_size_bytes

    return {"bytes": cache_size_bytes()}


def _cmd_clear_cache(_request: dict[str, Any]) -> Any:
    from .pipeline import cache_size_bytes, clear_cache

    freed = cache_size_bytes()
    clear_cache()
    return {"freed_bytes": freed}


def _model_job(request: dict[str, Any], out: IO[str], fn: Callable[..., Any]) -> Callable[[threading.Event], None]:
    return _job(request, out, lambda progress, cancelled: fn(progress, cancelled))


def _install_model(request: dict[str, Any], out: IO[str]) -> Callable[[threading.Event], None]:
    from . import models

    model_id = _require_str({"model": request.get("model", "deepfilternet3")}, "model")
    return _model_job(request, out, lambda progress, cancelled: {
        "path": str(models.install(model_id, progress=progress, cancelled=cancelled))})  # fmt: skip


def _install_hf(request: dict[str, Any], out: IO[str]) -> Callable[[threading.Event], None]:
    from . import models

    repo = _require_str(request, "repo")
    file = request.get("file")
    if file is not None:
        file = _require_str(request, "file")
    return _model_job(request, out, lambda progress, cancelled: models.install_hf(
        repo, file=file, progress=progress, cancelled=cancelled))  # fmt: skip


def _remove_model(request: dict[str, Any], out: IO[str]) -> Callable[[threading.Event], None]:
    from . import models

    model_id = _require_str(request, "model")
    return _model_job(request, out, lambda _p, _c: {"removed": models.remove(model_id)})


def handle(request: dict[str, Any], out: IO[str], tasks: Tasks) -> bool:
    """Atiende una petición sin bloquear. Devuelve False si el motor debe terminar."""
    req_id = request.get("id")
    cmd = request.get("cmd")

    try:
        if cmd == "ping":
            send(out, {"id": req_id, "ok": True, "result": "pong"})
        elif cmd == "health":
            send(out, {"id": req_id, "ok": True, "result": {"version": __version__}})
        elif cmd == "providers":
            tasks.start(req_id, _providers(request, out), out)
        elif cmd == "progress_demo":
            tasks.start(req_id, _progress_demo(request, out), out)
        elif cmd == "enhance":  # trabajo completo o, con `region`, vista previa
            tasks.start(req_id, _enhance(request, out), out, key=_job_key(request))
        elif cmd == "probe":
            tasks.start(req_id, _simple(request, out, _cmd_probe), out, key=_job_key(request))
        elif cmd == "waveform":
            tasks.start(req_id, _simple(request, out, _cmd_waveform), out, key=_job_key(request))
        elif cmd == "extract":
            tasks.start(req_id, _simple(request, out, _cmd_extract), out, key=_job_key(request))
        elif cmd == "preferred_providers":
            tasks.start(req_id, _simple(request, out, _cmd_preferred_providers), out, key=_job_key(request))
        elif cmd == "cache_info":
            tasks.start(req_id, _simple(request, out, _cmd_cache_info), out, key=_job_key(request))
        elif cmd == "clear_cache":
            tasks.start(req_id, _simple(request, out, _cmd_clear_cache), out, key=_job_key(request))
        elif cmd == "models_status":
            tasks.start(req_id, _simple(request, out, _cmd_models_status), out)
        elif cmd == "models_catalog":
            tasks.start(req_id, _simple(request, out, _cmd_models_catalog), out)
        elif cmd == "stage_catalog":
            tasks.start(req_id, _simple(request, out, _cmd_stage_catalog), out)
        elif cmd == "install_model":
            tasks.start(req_id, _install_model(request, out), out, key=_job_key(request))
        elif cmd == "install_hf":
            tasks.start(req_id, _install_hf(request, out), out, key=_job_key(request))
        elif cmd == "remove_model":
            tasks.start(req_id, _remove_model(request, out), out)
        elif cmd == "cancel":
            count = tasks.cancel(request.get("target"))
            send(out, {"id": req_id, "ok": True, "result": {"cancelled": count}})
        elif cmd == "shutdown":
            send(out, {"id": req_id, "ok": True, "result": "adios"})
            return False
        else:
            send(out, {"id": req_id, "ok": False, "error": f"comando desconocido: {cmd!r}"})
    except (ValueError, TypeError, KeyError) as exc:  # parámetros inválidos o mal tipados
        send(out, {"id": req_id, "ok": False, "error": f"parámetros inválidos: {exc}"})
    except Exception as exc:  # noqa: BLE001 - el hilo lector nunca debe morir por una petición
        send(out, {"id": req_id, "ok": False, "error": f"error interno: {type(exc).__name__}: {exc}"})
    return True


def serve(stdin: IO[str], stdout: IO[str]) -> None:
    """Lee peticiones hasta EOF o `shutdown`."""
    tasks = Tasks()

    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError as exc:
            send(stdout, {"id": None, "ok": False, "error": f"JSON inválido: {exc}"})
            continue
        if not isinstance(request, dict):
            send(stdout, {"id": None, "ok": False, "error": "la petición debe ser un objeto JSON"})
            continue
        if not handle(request, stdout, tasks):
            break

    # EOF o shutdown: se cancela lo que quede en curso y se sale.
    tasks.shutdown()


def main() -> None:
    # El código nativo (p. ej. ONNX Runtime al fallar DirectML) escribe en el fd 1 sin pasar por
    # Python y rompería el protocolo. Se reserva una copia del fd 1 solo para los mensajes JSON
    # y el fd 1 real se desvía a stderr.
    # Importa lo pesado (numpy, scipy, soundfile) en el hilo principal antes de atender peticiones:
    # importarlo por primera vez desde un hilo de trabajo se quedaba colgado en Windows (CI).
    import audio_enhancer_engine.pipeline  # noqa: F401

    protocol_fd = os.dup(1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    protocol = open(protocol_fd, "w", encoding="utf-8", newline="\n", buffering=1)  # noqa: SIM115
    # UTF-8 también en Windows; bytes inválidos en stdin no tumban el motor (se reemplazan).
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    serve(sys.stdin, protocol)
