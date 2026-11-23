"""Ajustes de un trabajo de mejora. Se serializan a JSON (presets) y se usan para el hash de checkpoints."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, fields
from typing import Any

SETTINGS_VERSION = 1
PIPELINE_VERSION = 2  # v2: etapa de separación y huellas de modelo en el hash; súbela al cambiar el algoritmo o el modelo: invalida los bloques en caché
SAMPLE_RATE = 48_000  # frecuencia interna fija (la que usa DeepFilterNet3)


@dataclass(frozen=True)
class Settings:
    """Todos los valores tienen un rango validado en `validate()`."""

    # Limpieza determinista
    highpass_hz: float | None = 80.0  # recorta graves inaudibles/ruido de viento; None = desactivado
    notch_hz: float | None = None  # zumbido eléctrico: 50 o 60 Hz; None = desactivado
    notch_harmonics: int = 3  # cuántos armónicos filtrar (f, 2f, 3f...)
    # Aislar voz / quitar fondo (modelo del catálogo, p. ej. "kim-vocal-2"); se aplica ANTES de la reducción de ruido
    separate_model: str | None = None
    separate_strength: float = 1.0  # 0 = solo audio original, 1 = solo voz aislada
    # Reducción de ruido por IA
    denoise: bool = True
    denoise_strength: float = 1.0  # 0 = solo audio original, 1 = solo audio limpiado
    # Volumen
    normalize: bool = True
    target_lufs: float = -16.0  # -16 online, -23 broadcast (EBU R128)
    max_true_peak_db: float = -1.0
    # Canales y salida
    channels: str = "each"  # "each": cada canal por separado; "mix": mezclar a mono
    output_format: str = "wav24"  # "wav24" | "flac24"
    version: int = SETTINGS_VERSION

    def validate(self) -> None:
        def check(cond: bool, msg: str) -> None:
            if not cond:
                raise ValueError(msg)

        def is_num(v: object) -> bool:
            return isinstance(v, (int, float)) and not isinstance(v, bool)

        check(self.highpass_hz is None or is_num(self.highpass_hz), "highpass_hz debe ser un número o None")
        check(self.notch_hz is None or is_num(self.notch_hz), "notch_hz debe ser un número o None")
        check(isinstance(self.notch_harmonics, int) and not isinstance(self.notch_harmonics, bool), "notch_harmonics debe ser entero")
        check(is_num(self.denoise_strength), "denoise_strength debe ser un número")
        check(is_num(self.separate_strength), "separate_strength debe ser un número")
        check(
            self.separate_model is None
            or (isinstance(self.separate_model, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,150}", self.separate_model)),
            "separate_model debe ser un identificador de modelo o None",
        )
        check(is_num(self.target_lufs) and is_num(self.max_true_peak_db), "target_lufs y max_true_peak_db deben ser números")
        check(isinstance(self.denoise, bool) and isinstance(self.normalize, bool), "denoise y normalize deben ser booleanos")

        check(self.highpass_hz is None or 10 <= self.highpass_hz <= 500, "highpass_hz debe estar entre 10 y 500")
        check(self.notch_hz is None or self.notch_hz in (50.0, 60.0), "notch_hz debe ser 50, 60 o None")
        check(1 <= self.notch_harmonics <= 6, "notch_harmonics debe estar entre 1 y 6")
        check(0.0 <= self.denoise_strength <= 1.0, "denoise_strength debe estar entre 0 y 1")
        check(0.0 <= self.separate_strength <= 1.0, "separate_strength debe estar entre 0 y 1")
        check(-40 <= self.target_lufs <= -5, "target_lufs debe estar entre -40 y -5")
        check(-6 <= self.max_true_peak_db <= 0, "max_true_peak_db debe estar entre -6 y 0")
        check(self.channels in ("each", "mix"), "channels debe ser 'each' o 'mix'")
        check(self.output_format in ("wav24", "flac24"), "output_format debe ser 'wav24' o 'flac24'")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        known = {f.name for f in fields(cls)}
        unknown = (set(data) - known) if isinstance(data, dict) else set()
        if unknown:
            raise ValueError(f"ajustes desconocidos: {sorted(unknown)}")
        if not isinstance(data, dict):
            raise TypeError("los ajustes deben ser un objeto")
        settings = cls(**data)
        settings.validate()
        return settings

    def processing_hash(self, model_fingerprints: dict[str, str] | None = None) -> str:
        """Hash de lo que afecta al audio de cada bloque (no al volumen final ni al formato de salida).

        Incluye la huella (sha256) de cada modelo usado: cambiar los pesos bajo el mismo id nunca mezcla caché.
        Una etapa desactivada tiene forma canónica (sus campos no entran en el hash).
        """
        relevant = {
            k: v
            for k, v in self.to_dict().items()
            if k not in ("normalize", "target_lufs", "max_true_peak_db", "output_format")
        }
        if self.separate_model is None:
            relevant.pop("separate_model")
            relevant.pop("separate_strength")
        if not self.denoise:
            relevant.pop("denoise_strength")
        relevant["models"] = dict(sorted((model_fingerprints or {}).items()))
        relevant["pipeline_version"] = PIPELINE_VERSION
        return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()[:16]
