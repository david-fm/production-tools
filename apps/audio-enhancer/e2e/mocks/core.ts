// Sustituto de @tauri-apps/api/core SOLO para las pruebas e2e en navegador: reenvía `engine_call` al puente
// (Node), que ejecuta el motor Python REAL. No se usa en la app empaquetada.
const BRIDGE = (globalThis as { __BRIDGE__?: string }).__BRIDGE__ ?? "http://127.0.0.1:4799";

export async function invoke<T>(cmd: string, args: Record<string, unknown> = {}): Promise<T> {
  const res = await fetch(`${BRIDGE}/invoke`, { method: "POST", body: JSON.stringify({ cmd, args }) });
  const body = (await res.json()) as { ok: boolean; result?: T; error?: string };
  if (!body.ok) throw body.error ?? "error";
  return body.result as T;
}

export function convertFileSrc(path: string): string {
  // Igual que Tauri: la ruta va codificada en el path, de modo que `?v=1` puede añadirse después.
  return `${BRIDGE}/file/${encodeURIComponent(path)}`;
}
