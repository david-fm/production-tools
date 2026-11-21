const BRIDGE = (globalThis as { __BRIDGE__?: string }).__BRIDGE__ ?? "http://127.0.0.1:4799";
export type UnlistenFn = () => void;

export async function listen<T>(event: string, handler: (e: { payload: T }) => void): Promise<UnlistenFn> {
  const source = new EventSource(`${BRIDGE}/events?name=${encodeURIComponent(event)}`);
  source.onmessage = (m) => handler({ payload: JSON.parse(m.data) as T });
  return () => source.close();
}
