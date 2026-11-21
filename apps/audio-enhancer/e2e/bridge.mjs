// Puente de pruebas: ejecuta el motor Python REAL y expone `engine_call`, eventos de progreso, archivos
// (con soporte de Range para <audio>) y diálogos simulados. Solo para e2e.
import { spawn } from "node:child_process";
import { createReadStream, mkdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { join, resolve } from "node:path";
import { createInterface } from "node:readline";

export function startBridge({ engineDir, cacheDir, workDir, openPath, saveDir, port = 4799, env = {} }) {
  let currentOpenPath = openPath;
  mkdirSync(cacheDir, { recursive: true });
  const engine = spawn("uv", ["run", "python", "-m", "audio_enhancer_engine"], {
    cwd: engineDir,
    env: { ...process.env, AUDIO_ENHANCER_WORK_DIR: workDir, ...env },
    stdio: ["pipe", "pipe", "inherit"],
  });
  let nextId = 0;
  const pending = new Map();
  const clients = new Set();
  createInterface({ input: engine.stdout }).on("line", (line) => {
    let msg;
    try { msg = JSON.parse(line); } catch { return; }
    if (msg.event === "progress") {
      for (const res of clients) res.write(`data: ${JSON.stringify(msg)}\n\n`);
    } else if (pending.has(msg.id)) {
      const { resolve: ok } = pending.get(msg.id);
      pending.delete(msg.id);
      ok(msg);
    }
  });

  const call = (cmd, params) =>
    new Promise((ok) => {
      const id = ++nextId;
      pending.set(id, { resolve: ok });
      engine.stdin.write(JSON.stringify({ ...params, id, cmd }) + "\n");
    });

  const cors = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*" };
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, `http://127.0.0.1:${port}`);
    if (req.method === "OPTIONS") { res.writeHead(204, cors).end(); return; }
    if (url.pathname === "/invoke") {
      let body = "";
      for await (const chunk of req) body += chunk;
      const { cmd, args } = JSON.parse(body);
      if (cmd !== "engine_call") { res.writeHead(200, cors).end(JSON.stringify({ ok: false, error: `comando ${cmd}` })); return; }
      const reply = await call(args.cmd, args.params ?? {});
      res.writeHead(200, { ...cors, "Content-Type": "application/json" });
      res.end(JSON.stringify(reply.ok ? { ok: true, result: reply.result } : { ok: false, error: reply.error }));
    } else if (url.pathname === "/events") {
      res.writeHead(200, { ...cors, "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
      clients.add(res);
      req.on("close", () => clients.delete(res));
    } else if (url.pathname === "/cachedir") {
      res.writeHead(200, cors).end(cacheDir);
    } else if (url.pathname === "/dialog/open") {
      res.writeHead(200, cors).end(JSON.stringify(currentOpenPath));
    } else if (url.pathname === "/dialog/save") {
      res.writeHead(200, cors).end(JSON.stringify(join(saveDir, url.searchParams.get("name") ?? "salida.wav")));
    } else if (url.pathname.startsWith("/file/")) {
      const path = resolve(decodeURIComponent(url.pathname.slice("/file/".length)));
      if (!path.startsWith(resolve(cacheDir) + "/")) { res.writeHead(403, cors).end(); return; } // mismo criterio que el scope de assets
      const size = statSync(path).size;
      const range = /bytes=(\d*)-(\d*)/.exec(req.headers.range ?? "");
      if (range) {
        const start = range[1] ? Number(range[1]) : 0;
        const end = range[2] ? Number(range[2]) : size - 1;
        res.writeHead(206, { ...cors, "Content-Type": "audio/wav", "Accept-Ranges": "bytes", "Content-Range": `bytes ${start}-${end}/${size}`, "Content-Length": end - start + 1 });
        createReadStream(path, { start, end }).pipe(res);
      } else {
        res.writeHead(200, { ...cors, "Content-Type": "audio/wav", "Accept-Ranges": "bytes", "Content-Length": size });
        createReadStream(path).pipe(res);
      }
    } else {
      res.writeHead(404, cors).end();
    }
  });
  return new Promise((ok) =>
    server.listen(port, "127.0.0.1", () =>
      ok({ setOpenPath: (p) => { currentOpenPath = p; }, close: () => { engine.kill(); server.close(); for (const c of clients) c.end(); } }),
    ),
  );
}
