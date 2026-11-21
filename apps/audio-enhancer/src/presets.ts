import { DEFAULT_SETTINGS, sanitizeSettings, type Settings } from "./settings";

export interface BuiltinPreset {
  id: string;
  settings: Settings;
}

const make = (over: Partial<Settings>): Settings => sanitizeSettings({ ...DEFAULT_SETTINGS, ...over });

export const BUILTIN_PRESETS: BuiltinPreset[] = [
  { id: "default", settings: make({}) },
  { id: "exterior", settings: make({ highpass_hz: 120, denoise_strength: 1 }) },
  { id: "estudio", settings: make({ highpass_hz: 80, denoise_strength: 0.6 }) },
  { id: "hum50", settings: make({ notch_hz: 50, denoise: false }) },
  { id: "hum60", settings: make({ notch_hz: 60, denoise: false }) },
  { id: "tv", settings: make({ target_lufs: -23 }) },
  { id: "volumen", settings: make({ highpass_hz: null, denoise: false }) },
];

// --- Preajustes propios (JSON versionado en localStorage; si no está disponible, solo viven en memoria) ---

const STORAGE_KEY = "audio-enhancer.presets";
const STORAGE_VERSION = 1;

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
    if (data.version !== STORAGE_VERSION || !Array.isArray(data.presets)) return [];
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
