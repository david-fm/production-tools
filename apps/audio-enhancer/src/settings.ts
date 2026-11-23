/** Ajustes del motor (espejo de engine/src/audio_enhancer_engine/settings.py). */
export interface Settings {
  highpass_hz: number | null;
  notch_hz: 50 | 60 | null;
  notch_harmonics: number;
  separate_model: string | null;
  separate_strength: number;
  denoise: boolean;
  denoise_strength: number;
  normalize: boolean;
  target_lufs: number;
  max_true_peak_db: number;
  channels: "each" | "mix";
  output_format: "wav24" | "flac24";
  version: number;
}

export const SETTINGS_VERSION = 1;

export const DEFAULT_SETTINGS: Settings = {
  highpass_hz: 80,
  notch_hz: null,
  notch_harmonics: 3,
  separate_model: null,
  separate_strength: 1,
  denoise: true,
  denoise_strength: 1,
  normalize: true,
  target_lufs: -16,
  max_true_peak_db: -1,
  channels: "each",
  output_format: "wav24",
  version: SETTINGS_VERSION,
};

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
/** Número finito o el valor por defecto (a diferencia de `||`, conserva el 0 válido). */
const num = (v: unknown, fallback: number): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);

/** Normaliza cualquier objeto (p. ej. un preajuste guardado) a ajustes válidos; lo desconocido se ignora. */
export function sanitizeSettings(input: Partial<Settings> | null | undefined): Settings {
  const s = { ...DEFAULT_SETTINGS, ...(input ?? {}) };
  return {
    highpass_hz: s.highpass_hz === null ? null : clamp(num(s.highpass_hz, 80), 10, 500),
    notch_hz: s.notch_hz === 50 || s.notch_hz === 60 ? s.notch_hz : null,
    notch_harmonics: Math.round(clamp(num(s.notch_harmonics, 3), 1, 6)),
    separate_model: typeof s.separate_model === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$/.test(s.separate_model) ? s.separate_model : null,
    separate_strength: clamp(num(s.separate_strength, 1), 0, 1),
    denoise: Boolean(s.denoise),
    denoise_strength: clamp(num(s.denoise_strength, 1), 0, 1),
    normalize: Boolean(s.normalize),
    target_lufs: clamp(num(s.target_lufs, -16), -40, -5),
    max_true_peak_db: clamp(num(s.max_true_peak_db, -1), -6, 0),
    channels: s.channels === "mix" ? "mix" : "each",
    output_format: s.output_format === "flac24" ? "flac24" : "wav24",
    version: SETTINGS_VERSION,
  };
}
