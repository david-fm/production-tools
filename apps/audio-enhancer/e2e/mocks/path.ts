const BRIDGE = (globalThis as { __BRIDGE__?: string }).__BRIDGE__ ?? "http://127.0.0.1:4799";
export async function appCacheDir(): Promise<string> {
  return (await (await fetch(`${BRIDGE}/cachedir`)).text()).trim();
}
export async function join(...parts: string[]): Promise<string> {
  return parts.join("/").replace(/\/+/g, "/");
}
