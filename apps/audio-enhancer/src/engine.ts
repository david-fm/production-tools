import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";

export interface EngineProgress {
  id: number;
  job?: string | null;
  value: number;
  stage?: string;
}

interface CallOptions {
  /** Identifica el trabajo para recibir su progreso y poder cancelarlo. */
  job?: string;
  /** Límite en segundos. Los trabajos largos pasan un valor grande; su avance se ve por eventos. */
  timeoutS?: number;
}

export const LONG_TIMEOUT_S = 60 * 60 * 24;

/** Envía un comando al motor (stdio JSON) y espera su respuesta. */
export async function engineCall<T = unknown>(
  cmd: string,
  params: Record<string, unknown> = {},
  options: CallOptions = {},
): Promise<T> {
  const merged = options.job ? { ...params, job: options.job } : params;
  return invoke<T>("engine_call", { cmd, params: merged, timeoutS: options.timeoutS });
}

export function cancelJob(job: string): Promise<unknown> {
  return engineCall("cancel", { target: job });
}

export function onEngineProgress(handler: (e: EngineProgress) => void): Promise<UnlistenFn> {
  return listen<EngineProgress>("engine-progress", (event) => handler(event.payload));
}
