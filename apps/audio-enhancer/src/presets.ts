import { DENOISE_MODEL, makeStage, sanitizeSettings, type Settings, type Stage } from "./settings";

export interface BuiltinPreset {
  id: string;
  /** Genera ajustes nuevos cada vez (las cajas llevan ids únicos). */
  build: () => Settings;
}

const withChain = (chain: Stage[], over: Partial<Settings> = {}): Settings => sanitizeSettings({ ...over, chain });
const hp = (hz: number) => makeStage("highpass", null, { hz });
const dn = (strength: number) => makeStage("model", DENOISE_MODEL, { strength });

export const BUILTIN_PRESETS: BuiltinPreset[] = [
  { id: "default", build: () => withChain([hp(80), dn(1)]) },
  { id: "exterior", build: () => withChain([hp(120), dn(1)]) },
  { id: "estudio", build: () => withChain([hp(80), dn(0.6)]) },
  { id: "hum50", build: () => withChain([makeStage("notch", null, { hz: 50 })]) },
  { id: "hum60", build: () => withChain([makeStage("notch", null, { hz: 60 })]) },
  { id: "tv", build: () => withChain([hp(80), dn(1)], { target_lufs: -23 }) },
  { id: "volumen", build: () => withChain([]) },
];

// --- Preajustes propios (JSON versionado en localStorage; si no está disponible, solo viven en memoria) ---

const STORAGE_KEY = "audio-enhancer.presets";
const STORAGE_VERSION = 2; // v1 guardaba ajustes planos: se migran a cadena al cargar

export interface CustomPreset {
  name: string;
  settings: Settings;
}

interface StoredPresets {
  version: number;
  presets: CustomPreset[];
}

export function loadCustomPresets(storage: Pick<Storage, "getItem"> | null = safeStorage()): CustomPreset[] {
  try {
    const raw = storage?.getItem(STORAGE_KEY);
    if (!raw) return [];
    const data = JSON.parse(raw) as StoredPresets;
    if ((data.version !== STORAGE_VERSION && data.version !== 1) || !Array.isArray(data.presets)) return [];
    return data.presets
      .filter((p) => typeof p?.name === "string" && p.name.trim() !== "")
      .map((p) => ({ name: p.name.trim().slice(0, 60), settings: sanitizeSettings(p.settings) }));
  } catch {
    return [];
  }
}

export function saveCustomPresets(
  presets: CustomPreset[],
  storage: Pick<Storage, "setItem"> | null = safeStorage(),
): boolean {
  try {
    const payload: StoredPresets = { version: STORAGE_VERSION, presets };
    storage?.setItem(STORAGE_KEY, JSON.stringify(payload));
    return storage !== null;
  } catch {
    return false;
  }
}

/** Añade o reemplaza (por nombre) un preajuste propio. */
export function upsertPreset(list: CustomPreset[], name: string, settings: Settings): CustomPreset[] {
  const clean = name.trim().slice(0, 60);
  if (!clean) return list;
  return [...list.filter((p) => p.name !== clean), { name: clean, settings: sanitizeSettings(settings) }];
}

function safeStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null; // p. ej. almacenamiento bloqueado: los preajustes solo viven en memoria
  }
}
