/** Ajustes del motor (espejo de engine/src/audio_enhancer_engine/settings.py). */

export type StageKind = "highpass" | "notch" | "model";
export type ParamValue = number | string;

/** Una caja de la cadena. `id` identifica la instancia (se pueden repetir cajas del mismo tipo). */
export interface Stage {
  id: string;
  kind: StageKind;
  model?: string | null;
  enabled: boolean;
  params: Record<string, ParamValue>;
}

export interface Settings {
  /** Cadena ordenada: la salida de cada caja es la entrada de la siguiente. */
  chain: Stage[];
  normalize: boolean;
  target_lufs: number;
  max_true_peak_db: number;
  channels: "each" | "mix";
  output_format: "wav24" | "flac24";
  version: number;
}

export const SETTINGS_VERSION = 2;
export const MAX_STAGES = 12;
export const DENOISE_MODEL = "deepfilternet3";

let idCounter = 0;
export function newStageId(): string {
  idCounter += 1;
  return `s${Date.now().toString(36)}${idCounter}`;
}

/** Parámetros por defecto (los mismos que el esquema del motor; el motor valida de todas formas). */
export function defaultParams(kind: StageKind): Record<string, ParamValue> {
  if (kind === "highpass") return { hz: 80 };
  if (kind === "notch") return { hz: 50, harmonics: 3 };
  return { strength: 1 };
}

export function makeStage(kind: StageKind, model?: string | null, params: Record<string, ParamValue> = {}): Stage {
  return { id: newStageId(), kind, model: kind === "model" ? (model ?? null) : null, enabled: true, params: { ...defaultParams(kind), ...params } };
}

/** Cadena equivalente a «Equilibrado»: recorte de graves y reducción de ruido. */
export const defaultChain = (): Stage[] => [makeStage("highpass"), makeStage("model", DENOISE_MODEL)];

export const DEFAULT_SETTINGS: Settings = {
  chain: [],
  normalize: true,
  target_lufs: -16,
  max_true_peak_db: -1,
  channels: "each",
  output_format: "wav24",
  version: SETTINGS_VERSION,
};
/** Ajustes por defecto con una cadena nueva (los ids deben ser únicos por sesión). */
export const freshDefaults = (): Settings => ({ ...DEFAULT_SETTINGS, chain: defaultChain() });

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));
/** Número finito o el valor por defecto (a diferencia de `||`, conserva el 0 válido). */
const num = (v: unknown, fallback: number): number => (typeof v === "number" && Number.isFinite(v) ? v : fallback);
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$/;

function sanitizeStage(input: unknown, used: Set<string>): Stage | null {
  if (typeof input !== "object" || input === null) return null;
  const s = input as Partial<Stage>;
  if (s.kind !== "highpass" && s.kind !== "notch" && s.kind !== "model") return null;
  if (s.kind === "model" && !(typeof s.model === "string" && MODEL_ID.test(s.model))) return null;
  const p = (s.params ?? {}) as Record<string, unknown>;
  let params: Record<string, ParamValue>;
  if (s.kind === "highpass") params = { hz: clamp(num(p.hz, 80), 10, 500) };
  else if (s.kind === "notch") params = { hz: p.hz === 60 ? 60 : 50, harmonics: Math.round(clamp(num(p.harmonics, 3), 1, 6)) };
  else {
    params = { strength: clamp(num(p.strength, 1), 0, 1) };
    if (p.keep === "residual" || p.keep === "primary") params.keep = p.keep;
  }
  let id = typeof s.id === "string" && /^[A-Za-z0-9][A-Za-z0-9._-]{0,150}$/.test(s.id) ? s.id : newStageId();
  while (used.has(id)) id = newStageId();
  used.add(id);
  return { id, kind: s.kind, model: s.kind === "model" ? (s.model as string) : null, enabled: s.enabled !== false, params };
}

/** Migra los ajustes planos de v0.1.0/v0.2.0 a cadena, conservando el orden efectivo de entonces. */
function chainFromFlat(f: Record<string, unknown>): Stage[] {
  const out: Stage[] = [];
  if (f.highpass_hz !== null && f.highpass_hz !== undefined) out.push(makeStage("highpass", null, { hz: clamp(num(f.highpass_hz, 80), 10, 500) }));
  if (f.notch_hz === 50 || f.notch_hz === 60) out.push(makeStage("notch", null, { hz: f.notch_hz, harmonics: Math.round(clamp(num(f.notch_harmonics, 3), 1, 6)) }));
  if (typeof f.separate_model === "string" && MODEL_ID.test(f.separate_model)) {
    out.push(makeStage("model", f.separate_model, { strength: clamp(num(f.separate_strength, 1), 0, 1) }));
  }
  if (f.denoise !== false) out.push(makeStage("model", DENOISE_MODEL, { strength: clamp(num(f.denoise_strength, 1), 0, 1) }));
  return out;
}

/** Normaliza cualquier objeto (p. ej. un preajuste guardado, nuevo o antiguo) a ajustes válidos. */
export function sanitizeSettings(input: unknown): Settings {
  const s = (typeof input === "object" && input !== null ? input : {}) as Record<string, unknown>;
  let chain: Stage[];
  if (Array.isArray(s.chain)) {
    const used = new Set<string>();
    chain = s.chain.map((st) => sanitizeStage(st, used)).filter((st): st is Stage => st !== null).slice(0, MAX_STAGES);
  } else if ("highpass_hz" in s || "denoise" in s || "notch_hz" in s || "separate_model" in s) {
    chain = chainFromFlat(s);
  } else {
    chain = defaultChain();
  }
  return {
    chain,
    normalize: s.normalize === undefined ? true : Boolean(s.normalize),
    target_lufs: clamp(num(s.target_lufs, -16), -40, -5),
    max_true_peak_db: clamp(num(s.max_true_peak_db, -1), -6, 0),
    channels: s.channels === "mix" ? "mix" : "each",
    output_format: s.output_format === "flac24" ? "flac24" : "wav24",
    version: SETTINGS_VERSION,
  };
}

/** Lo que se envía al motor. */
export function toEngineSettings(s: Settings): Settings {
  return { ...s, version: SETTINGS_VERSION };
}

/** Clave para saber si dos ajustes producen el mismo audio (ignora los ids de las instancias). */
export function settingsFingerprint(s: Settings): string {
  return JSON.stringify({
    chain: s.chain.map(({ kind, model, enabled, params }) => ({ kind, model: model ?? null, enabled, params })),
    n: s.normalize, t: s.target_lufs, p: s.max_true_peak_db, c: s.channels, f: s.output_format,
  });
}
