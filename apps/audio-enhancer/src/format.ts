export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

export function fileName(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

/**
 * Volúmenes (0..1) para comparar A/B sin que lo más fuerte parezca mejor:
 * se atenúa el más fuerte hasta igualar al más débil. `null` = no se pudo medir => sin compensación.
 */
export function compensatedVolumes(
  originalLufs: number | null,
  enhancedLufs: number | null,
  enabled: boolean,
): { original: number; enhanced: number } {
  if (!enabled || originalLufs === null || enhancedLufs === null) return { original: 1, enhanced: 1 };
  const delta = enhancedLufs - originalLufs; // >0: el mejorado suena más fuerte
  const atten = 10 ** (-Math.abs(delta) / 20);
  return delta > 0 ? { original: 1, enhanced: atten } : { original: atten, enhanced: 1 };
}

export const MAX_PREVIEW_S = 60;

/** Ajusta una selección a la duración y al máximo permitido; mínimo 1 s. */
export function clampRegion(start: number, end: number, duration: number): [number, number] {
  let a = Math.max(0, Math.min(start, end));
  let b = Math.min(duration, Math.max(start, end));
  if (b - a < 1) b = Math.min(duration, a + 1);
  if (b - a < 1) a = Math.max(0, b - 1);
  if (b - a > MAX_PREVIEW_S) b = a + MAX_PREVIEW_S;
  return [a, b];
}
