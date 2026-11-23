"""Catálogo y gestor de modelos. NINGÚN modelo viaja en el instalador: todo se descarga del origen.

- Catálogo fijo (con sha256) + modelos `.onnx` de Hugging Face fuera del catálogo (no verificados).
- Instalación atómica: descarga a una carpeta temporal, verifica y publica con un único rename.
- Marcador `.ok` con la huella (sha256) del modelo. Compatible con v0.1.0, cuyo marcador de
  DeepFilterNet3 guarda el sha256 del paquete.
- Cada trabajo "reserva" los modelos que usa (`use_models`): no se pueden quitar ni reinstalar mientras tanto.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import tarfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MARKER = ".ok"
INFO = "model.json"  # metadatos de modelos de HF
HF_API = "https://huggingface.co/api/models/"
HF_HOST_SUFFIXES = ("huggingface.co", "hf.co")
HF_MAX_FILE_BYTES = 1_000_000_000
HF_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
DISK_MARGIN = 1.2

Progress = Callable[[float, str], None]
Cancelled = Callable[[], bool]


class ModelError(Exception):
    """Error legible para el usuario."""


@dataclass(frozen=True)
class DownloadFile:
    name: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ModelEntry:
    id: str
    name: str
    task: str  # "denoise" | "separate"
    description: str
    license: str
    license_url: str
    verified_license: bool
    default: bool
    size_bytes: int
    files: tuple[DownloadFile, ...]
    archive: bool = False  # el único fichero es un .tar.gz con los ficheros de `extract`
    extract: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        return self.files[0].sha256

    @property
    def required_files(self) -> tuple[str, ...]:
        return self.extract if self.archive else tuple(f.name for f in self.files)


DFN3 = ModelEntry(
    id="deepfilternet3",
    name="DeepFilterNet3",
    task="denoise",
    description="Reduce ruido de fondo (ventiladores, aire acondicionado, hiss) conservando la voz.",
    license="MIT / Apache-2.0",
    license_url="https://github.com/Rikorose/DeepFilterNet",
    verified_license=True,
    default=True,
    size_bytes=8_000_000,
    files=(
        DownloadFile(
            "DeepFilterNet3_onnx.tar.gz",
            "https://github.com/Rikorose/DeepFilterNet/raw/main/models/DeepFilterNet3_onnx.tar.gz",
            "c94d91f70911001c946e0fabb4aa9adc37045f45a03b56008cb0c8244cb63616",
            8_000_000,
        ),
    ),
    archive=True,
    extract=("enc.onnx", "erb_dec.onnx", "df_dec.onnx", "config.ini"),
)

KIM_VOCAL_2 = ModelEntry(
    id="kim-vocal-2",
    name="Kim Vocal 2 (aislar voz)",
    task="separate",
    description="Aísla la voz y retira música o sonido de fondo. Modelo MDX-Net de Ultimate Vocal Remover.",
    license="Sin verificar (el espejo declara MIT)",
    license_url="https://huggingface.co/seanghay/uvr_models",
    verified_license=False,
    default=False,
    size_bytes=66_759_214,
    files=(
        DownloadFile(
            "Kim_Vocal_2.onnx",
            "https://huggingface.co/seanghay/uvr_models/resolve/6f4fc0cfb0717c9033ffed12471a53008f145b20/Kim_Vocal_2.onnx",
            "ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b",
            66_759_214,
        ),
    ),
    params={"adapter": "mdx", "n_fft": 7680, "dim_f": 3072, "dim_t": 256, "compensate": 1.009, "keep": "primary"},
)

CATALOG: dict[str, ModelEntry] = {e.id: e for e in (DFN3, KIM_VOCAL_2)}

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}
_usage: dict[str, int] = {}


def _lock_for(model_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(model_id, threading.Lock())


# ---------- rutas y estado ----------


def default_models_dir() -> Path:
    override = os.environ.get("AUDIO_ENHANCER_MODELS_DIR")
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/Library/Application Support")
    return Path(base) / "AudioEnhancer" / "models"


def model_folder(model_id: str = "deepfilternet3", models_dir: Path | None = None) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", model_id) or model_id.startswith("."):
        raise ModelError(f"Identificador de modelo inválido: {model_id!r}")
    return (models_dir or default_models_dir()) / model_id


def _marker(folder: Path) -> str | None:
    try:
        return (folder / MARKER).read_text().strip()
    except OSError:
        return None


def _read_info(folder: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((folder / INFO).read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def entry_status(entry: ModelEntry, models_dir: Path | None = None) -> str:
    """'installed' | 'missing' | 'outdated' (instalado con otra huella que el catálogo)."""
    folder = model_folder(entry.id, models_dir)
    mark = _marker(folder)
    if mark is None or not all((folder / f).is_file() for f in entry.required_files):
        return "missing"
    return "installed" if mark == entry.fingerprint else "outdated"


def is_installed(folder: Path) -> bool:
    """Compatibilidad con v0.1.0: DeepFilterNet3 instalado con la huella correcta."""
    return folder.name == DFN3.id and entry_status(CATALOG[DFN3.id], folder.parent) == "installed"


# ---------- seguridad de modelos ONNX no catalogados ----------


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = value = 0
    while True:
        b = buf[i]
        i += 1
        value |= (b & 0x7F) << shift
        if not b & 0x80:
            return value, i
        shift += 7


def _fields(buf: bytes, start: int = 0, end: int | None = None) -> Iterator[tuple[int, int, int, int]]:
    """Recorre un mensaje protobuf: (campo, tipo_wire, inicio, fin) del valor (sin copiar)."""
    i, end = start, len(buf) if end is None else end
    while i < end:
        key, i = _varint(buf, i)
        field_no, wire = key >> 3, key & 7
        if wire == 0:
            value, j = _varint(buf, i)
            yield field_no, wire, value, j
            i = j
        elif wire == 2:
            length, j = _varint(buf, i)
            yield field_no, wire, j, j + length
            i = j + length
        elif wire == 1:
            yield field_no, wire, i, i + 8
            i += 8
        elif wire == 5:
            yield field_no, wire, i, i + 4
            i += 4
        else:
            raise ValueError("protobuf inválido")


SAFE_DOMAINS = {"", "ai.onnx", "ai.onnx.ml", "com.microsoft"}


def check_onnx_safe(path: Path) -> None:
    """Rechaza `.onnx` con datos externos o con operadores de dominios personalizados.

    ONNX Runtime no carga librerías nativas de operadores sin registro explícito; aun así se
    rechaza cualquier dominio desconocido y cualquier tensor con `external_data`.
    """
    buf = path.read_bytes()
    try:
        for fno, wire, a, b in _fields(buf):
            if fno == 8 and wire == 2:  # opset_import
                for f2, w2, a2, b2 in _fields(buf, a, b):
                    if f2 == 1 and w2 == 2 and buf[a2:b2].decode("utf-8", "replace") not in SAFE_DOMAINS:
                        raise ModelError(f"El modelo usa un dominio de operadores no permitido: {buf[a2:b2].decode('utf-8','replace')!r}.")
            if fno == 7 and wire == 2:  # graph
                for g, gw, ga, gb in _fields(buf, a, b):
                    if g == 1 and gw == 2:  # node
                        for n, nw, na, nb in _fields(buf, ga, gb):
                            if n == 7 and nw == 2 and buf[na:nb].decode("utf-8", "replace") not in SAFE_DOMAINS:
                                raise ModelError("El modelo usa operadores personalizados; no se carga.")
                    if g == 5 and gw == 2:  # initializer (TensorProto)
                        for t, tw, ta, tb in _fields(buf, ga, gb):
                            if t == 13 or (t == 14 and tw == 0 and ta == 1):
                                raise ModelError("El modelo usa datos externos (external_data); no se carga.")
    except (ValueError, IndexError) as exc:
        raise ModelError("El archivo no es un modelo ONNX válido.") from exc


# ---------- descarga ----------


class _HostRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed: Callable[[str], bool]) -> None:
        self._allowed = allowed

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self._allowed(newurl):
            raise ModelError(f"Redirección a un servidor no permitido: {urllib.parse.urlparse(newurl).hostname}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _hf_allowed(url: str) -> bool:
    parts = urllib.parse.urlparse(url)
    host = parts.hostname or ""
    return parts.scheme == "https" and any(host == s or host.endswith("." + s) for s in HF_HOST_SUFFIXES)


def _open(url: str, allowed: Callable[[str], bool] | None):
    if allowed is not None and not allowed(url):
        raise ModelError(f"Servidor no permitido: {urllib.parse.urlparse(url).hostname}")
    handlers: list[Any] = [_HostRedirects(allowed)] if allowed is not None else []
    opener = urllib.request.build_opener(*handlers)
    return opener.open(urllib.request.Request(url, headers={"User-Agent": "audio-enhancer"}), timeout=60)


def _download(
    url: str, dest: Path, max_bytes: int, progress: Progress, base: float, span: float, cancelled: Cancelled,
    allowed: Callable[[str], bool] | None = None,
) -> str:
    """Descarga en streaming con tope de bytes (también sin Content-Length). Devuelve el sha256."""
    digest, total = hashlib.sha256(), 0
    try:
        with _open(url, allowed) as resp, dest.open("wb") as out:
            length = int(resp.headers.get("Content-Length") or 0)
            if length > max_bytes:
                raise ModelError("La descarga supera el tamaño esperado; se descartó.")
            while chunk := resp.read(1 << 20):
                if cancelled():
                    raise ModelError("cancelado")
                total += len(chunk)
                if total > max_bytes:
                    raise ModelError("La descarga supera el tamaño esperado; se descartó.")
                digest.update(chunk)
                out.write(chunk)
                progress(base + span * min(1.0, total / max(length or max_bytes, 1)), "descargando")
    except urllib.error.URLError as exc:
        raise ModelError(f"No se pudo descargar: {exc.reason}") from exc
    return digest.hexdigest()


def _check_disk(models_dir: Path, needed: int) -> None:
    models_dir.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(models_dir).free
    if free < needed * DISK_MARGIN:
        raise ModelError(f"Espacio insuficiente: se necesitan ~{needed * DISK_MARGIN / 1e6:.0f} MB y hay {free / 1e6:.0f} MB.")


def _publish(tmp: Path, target: Path) -> None:
    shutil.rmtree(target, ignore_errors=True)
    os.replace(tmp, target)


def install(
    model_id: str, progress: Progress | None = None, cancelled: Cancelled | None = None,
    models_dir: Path | None = None, allow_http_for_tests: bool = False,
) -> Path:
    """Instala (o reinstala si está desactualizado) un modelo del catálogo, verificando sha256."""
    entry = CATALOG.get(model_id)
    if entry is None:
        raise ModelError(f"Modelo desconocido: {model_id}")
    progress, cancelled = progress or (lambda *_: None), cancelled or (lambda: False)
    base = models_dir or default_models_dir()
    target = model_folder(entry.id, base)
    with _lock_for(entry.id):  # una segunda petición del mismo id espera y luego ve el resultado
        if entry_status(entry, base) == "installed":
            return target
        if _usage.get(entry.id):
            raise ModelError("El modelo está en uso por un trabajo en curso.")
        _check_disk(base, entry.size_bytes)
        tmp = base / f".{entry.id}.{uuid.uuid4().hex}.tmp"
        tmp.mkdir()
        try:
            n = len(entry.files)
            for i, f in enumerate(entry.files):
                part = tmp / (f.name + ".part")
                got = _download(f.url, part, int(f.size * 1.1) + (1 << 20), progress, i / n, 0.9 / n, cancelled,
                                allowed=(lambda u: True) if allow_http_for_tests else None)  # fmt: skip
                if got != f.sha256:
                    raise ModelError(f"sha256 de {f.name} no coincide (esperado {f.sha256}, recibido {got}).")
                if entry.archive:
                    _extract(part, tmp, entry.extract)
                    part.unlink()
                else:
                    os.replace(part, tmp / f.name)
            missing = [f for f in entry.required_files if not (tmp / f).is_file()]
            if missing:
                raise ModelError(f"El paquete del modelo no contiene: {missing}")
            (tmp / MARKER).write_text(entry.fingerprint)
            _publish(tmp, target)
            progress(1.0, "listo")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return target


def _extract(archive: Path, dest: Path, wanted: tuple[str, ...]) -> None:
    with tarfile.open(archive, mode="r:gz") as tar:
        for member in tar.getmembers():
            name = os.path.basename(member.name)  # nunca se usa la ruta del archivo: sin path traversal
            if member.isfile() and name in wanted:
                data = tar.extractfile(member)
                assert data is not None
                (dest / name).write_bytes(data.read())


def ensure_deepfilternet3(models_dir: Path | None = None) -> Path:
    """Compatibilidad con v0.1.0."""
    return install("deepfilternet3", models_dir=models_dir)


# ---------- Hugging Face (fuera del catálogo; solo .onnx) ----------


def hf_folder_id(repo: str, file: str) -> str:
    owner, name = repo.split("/")
    stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file).stem)[:60]
    return f"hf--{owner}--{name}--{stem}"


def install_hf(
    repo: str, file: str | None = None, progress: Progress | None = None, cancelled: Cancelled | None = None,
    models_dir: Path | None = None, api_base: str = HF_API, allowed: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Descarga un `.onnx` de un repo de HF, fijando la revisión (commit) resuelta. No verificado."""
    if not isinstance(repo, str) or not HF_REPO_RE.fullmatch(repo) or ".." in repo:
        raise ModelError("Repositorio inválido: usa el formato usuario/nombre.")
    progress, cancelled = progress or (lambda *_: None), cancelled or (lambda: False)
    allowed = allowed or _hf_allowed
    base = models_dir or default_models_dir()
    try:
        with _open(api_base + repo + "?blobs=true", allowed) as resp:
            meta = json.loads(resp.read(5_000_000))
    except (urllib.error.URLError, ValueError) as exc:
        raise ModelError(f"No se pudo consultar el repositorio: {exc}") from exc
    revision = meta.get("sha")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ModelError("El repositorio no devolvió una revisión válida.")
    onnx = [s for s in meta.get("siblings", []) if str(s.get("rfilename", "")).endswith(".onnx")]
    if file is not None:
        onnx = [s for s in onnx if s["rfilename"] == file]
    if not onnx:
        raise ModelError("El repositorio no contiene ningún archivo .onnx (solo se aceptan .onnx).")
    if len(onnx) > 1:
        names = ", ".join(s["rfilename"] for s in onnx[:8])
        raise ModelError(f"Hay varios .onnx; indica cuál instalar. Disponibles: {names}")
    pick = onnx[0]
    rel = pick["rfilename"]
    if "/" in rel or ".." in rel or not re.fullmatch(r"[A-Za-z0-9._ -]+", rel):
        raise ModelError("Nombre de archivo no permitido.")
    size = int(pick.get("size") or 0)
    if size <= 0 or size > HF_MAX_FILE_BYTES:
        raise ModelError("Tamaño del modelo ausente o por encima del límite.")
    license_ = ""
    card = meta.get("cardData") or {}
    if isinstance(card, dict):
        license_ = str(card.get("license") or "")[:80]
    model_id = hf_folder_id(repo, rel)
    target = model_folder(model_id, base)
    with _lock_for(model_id):
        if _usage.get(model_id):
            raise ModelError("El modelo está en uso por un trabajo en curso.")
        _check_disk(base, size)
        tmp = base / f".{model_id}.{uuid.uuid4().hex}.tmp"
        tmp.mkdir()
        try:
            url = f"https://huggingface.co/{repo}/resolve/{revision}/{urllib.parse.quote(rel)}"
            if api_base != HF_API:  # solo tests: el servidor local sirve el archivo desde la misma base
                url = f"{api_base.rstrip('/')}/files/{revision}/{urllib.parse.quote(rel)}"
            digest = _download(url, tmp / rel, size + (1 << 20), progress, 0.0, 0.9, cancelled, allowed=allowed)
            check_onnx_safe(tmp / rel)
            info = {"source": "huggingface", "repo": repo, "revision": revision, "file": rel, "sha256": digest,
                    "license": license_ or "desconocida", "verified_license": False, "size_bytes": size}  # fmt: skip
            (tmp / INFO).write_text(json.dumps(info))
            (tmp / MARKER).write_text(digest)
            _publish(tmp, target)
            progress(1.0, "listo")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return {"id": model_id, **info}


# ---------- listado, uso y borrado ----------


def list_models(models_dir: Path | None = None) -> list[dict[str, Any]]:
    base = models_dir or default_models_dir()
    out: list[dict[str, Any]] = []
    for e in CATALOG.values():
        out.append({
            "id": e.id, "name": e.name, "task": e.task, "description": e.description, "license": e.license,
            "license_url": e.license_url, "verified_license": e.verified_license, "default": e.default,
            "size_bytes": e.size_bytes, "status": entry_status(e, base), "source": "catalog",
            "in_use": bool(_usage.get(e.id)),
        })  # fmt: skip
    if base.is_dir():
        for folder in sorted(base.glob("hf--*")):
            info = _read_info(folder)
            if info and _marker(folder) == info.get("sha256") and (folder / info["file"]).is_file():
                out.append({
                    "id": folder.name, "name": f"{info['repo']} · {info['file']}", "task": "unknown",
                    "description": "Modelo de Hugging Face sin verificar.", "license": info.get("license", "desconocida"),
                    "license_url": f"https://huggingface.co/{info['repo']}", "verified_license": False, "default": False,
                    "size_bytes": info.get("size_bytes", 0), "status": "installed", "source": "huggingface",
                    "in_use": bool(_usage.get(folder.name)),
                })  # fmt: skip
    return out


def remove(model_id: str, models_dir: Path | None = None) -> bool:
    folder = model_folder(model_id, models_dir)
    with _lock_for(model_id):
        if _usage.get(model_id):
            raise ModelError("El modelo está en uso por un trabajo en curso; espera a que termine.")
        existed = folder.exists()
        shutil.rmtree(folder, ignore_errors=True)
    return existed


@contextlib.contextmanager
def use_models(ids: list[str], models_dir: Path | None = None) -> Iterator[None]:
    """Reserva los modelos mientras dura un trabajo: no se pueden quitar ni reinstalar."""
    base = models_dir or default_models_dir()
    taken: list[str] = []
    try:
        for model_id in ids:
            lock = _lock_for(model_id)
            if lock.locked():
                raise ModelError(f"El modelo {model_id} se está instalando; espera a que termine.")
            folder = model_folder(model_id, base)
            if _marker(folder) is None:
                raise ModelError(f"El modelo {model_id} no está instalado.")
            with _locks_guard:
                _usage[model_id] = _usage.get(model_id, 0) + 1
            taken.append(model_id)
        yield
    finally:
        with _locks_guard:
            for model_id in taken:
                _usage[model_id] -= 1
                if _usage[model_id] <= 0:
                    del _usage[model_id]


def model_fingerprint(model_id: str, models_dir: Path | None = None) -> str:
    """Huella del modelo instalado (para el hash de caché: cambiar pesos nunca mezcla bloques)."""
    mark = _marker(model_folder(model_id, models_dir))
    if mark is None:
        raise ModelError(f"El modelo {model_id} no está instalado.")
    return mark

