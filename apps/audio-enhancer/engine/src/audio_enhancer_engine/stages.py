"""Construye la cadena de etapas (separar -> reducir ruido) a partir de los ajustes y los modelos instalados."""

from __future__ import annotations

import threading
from typing import Any

from . import models
from .denoise import Chain, DeepFilterNet3
from .mdx import MdxNet, MdxParams
from .models import ModelError

_cache: dict[tuple[str, str], Any] = {}
_lock = threading.Lock()


def needed_models(settings) -> list[str]:
    ids: list[str] = []
    if settings.separate_model is not None and settings.separate_strength > 0:
        ids.append(settings.separate_model)
    if settings.denoise and settings.denoise_strength > 0:
        ids.append("deepfilternet3")
    return ids


def _mdx_params_for_hf(path: str) -> MdxParams:
    import onnxruntime as ort

    shape = ort.InferenceSession(path, providers=["CPUExecutionProvider"]).get_inputs()[0].shape
    if len(shape) == 4 and shape[1] == 4 and all(isinstance(d, int) for d in shape[2:]):
        dim_f, dim_t = shape[2], shape[3]
        n_fft = 6144 if dim_f == 3072 else 2 * dim_f
        return MdxParams(n_fft=n_fft, dim_f=dim_f, dim_t=dim_t, compensate=1.0)
    raise ModelError(
        "Modelo descargado pero no compatible: la app solo sabe ejecutar modelos MDX-Net (entrada [N,4,F,T])."
    )


def load_model(model_id: str, models_dir=None):
    """Carga (con caché) un modelo instalado. La caché usa la huella: cambiar pesos recarga."""
    fingerprint = models.model_fingerprint(model_id, models_dir)
    key = (model_id, fingerprint)
    with _lock:
        if key in _cache:
            return _cache[key]
        folder = models.model_folder(model_id, models_dir)
        if model_id == "deepfilternet3":
            loaded: Any = DeepFilterNet3(folder)
        elif model_id in models.CATALOG:
            p = models.CATALOG[model_id].params
            if p.get("adapter") != "mdx":
                raise ModelError(f"El modelo {model_id} no tiene adaptador.")
            loaded = MdxNet(str(folder / models.CATALOG[model_id].files[0].name),
                            MdxParams(p["n_fft"], p["dim_f"], p["dim_t"], p["compensate"], p["keep"]))  # fmt: skip
        else:
            info = models._read_info(folder)
            if not info:
                raise ModelError(f"El modelo {model_id} no tiene metadatos.")
            path = str(folder / info["file"])
            models.check_onnx_safe(folder / info["file"])  # también al cargar, no solo al instalar
            loaded = MdxNet(path, _mdx_params_for_hf(path))
        _cache[key] = loaded
        return loaded


def build_chain(settings, models_dir=None) -> Chain | None:
    """Cadena para estos ajustes, o None si no hay etapas de IA. Los modelos deben estar reservados (use_models)."""
    ids = needed_models(settings)
    if not ids:
        return None
    stages, fingerprints, providers = [], {}, []
    for model_id in ids:
        model = load_model(model_id, models_dir)
        strength = settings.separate_strength if model_id == settings.separate_model else settings.denoise_strength
        stages.append((model, strength))
        fingerprints[model_id] = models.model_fingerprint(model_id, models_dir)
        providers.extend(p for p in model.providers if p not in providers)
    return Chain(stages, fingerprints, providers)
