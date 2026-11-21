const BRIDGE = (globalThis as { __BRIDGE__?: string }).__BRIDGE__ ?? "http://127.0.0.1:4799";
export async function open(): Promise<string | null> {
  return (await (await fetch(`${BRIDGE}/dialog/open`)).json()) as string | null;
}
export async function save(options: { defaultPath?: string }): Promise<string | null> {
  const name = options.defaultPath ?? "salida.wav";
  return (await (await fetch(`${BRIDGE}/dialog/save?name=${encodeURIComponent(name)}`)).json()) as string | null;
}
