// Prueba e2e en navegador (Chromium) de la interfaz REAL contra el motor Python REAL.
// La capa de Tauri (Rust, WebView, diálogos nativos) se sustituye por mocks: lo que NO cubre se prueba a mano.
// Uso:  node e2e/run.mjs [carpeta_de_capturas]
import { execFileSync, spawn } from "node:child_process";
import { existsSync, mkdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { startBridge } from "./bridge.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const app = resolve(here, "..");
const out = resolve(process.argv[2] ?? join(tmpdir(), "audio-enhancer-e2e"));
const work = join(out, "work");
rmSync(work, { recursive: true, force: true });
mkdirSync(work, { recursive: true });

// --- Audio de prueba: voz sintética (si hay `say`) + ruido rosa, con nombre con tildes y espacios ---
const sample = join(work, "entrevista de prueba ñandú.wav");
const noise = ["-f", "lavfi", "-i", "anoisesrc=d=40:a=0.04:c=pink:r=48000"];
if (process.platform === "darwin") {
  const text = "Buenas tardes. Hoy vamos a probar la herramienta de mejora de audio. ".repeat(6);
  execFileSync("say", ["-o", join(work, "voz.aiff"), text]);
  execFileSync("ffmpeg", ["-v", "error", "-y", "-i", join(work, "voz.aiff"), ...noise, "-filter_complex",
    "[0:a]aresample=48000,volume=0.6[v];[v][1:a]amix=inputs=2:duration=first:normalize=0", "-t", "40", sample]);
} else {
  execFileSync("ffmpeg", ["-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=200:d=40", ...noise, "-filter_complex",
    "amix=inputs=2:duration=first", sample]);
}

const bridge = await startBridge({
  engineDir: join(app, "engine"), cacheDir: join(work, "cache"), workDir: join(work, "engine-work"),
  openPath: sample, saveDir: join(work, "salidas"),
});
mkdirSync(join(work, "salidas"), { recursive: true });
const vite = spawn("npx", ["vite", "--config", "e2e/vite.e2e.config.ts"], { cwd: app, stdio: "ignore" });
await new Promise((r) => setTimeout(r, 4000));

const failures = [];
const check = (cond, msg) => { if (!cond) failures.push(msg); console.log(`${cond ? "OK  " : "FALLA"} ${msg}`); };
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e)));
  page.on("console", (m) => m.type() === "error" && pageErrors.push(m.text()));
  await page.goto("http://localhost:1421");

  await page.getByText(/Motor de audio listo/).waitFor({ timeout: 60_000 });
  check(true, "el motor responde y la interfaz lo muestra");
  check(await page.getByRole("heading", { name: "Cómo funciona" }).isVisible(), "la pantalla inicial explica cómo funciona");
  await page.screenshot({ path: join(out, "01-inicio.png") });

  await page.getByRole("button", { name: /Abrir archivo/ }).click();
  await page.getByRole("img", { name: "Fragmento de prueba" }).waitFor({ timeout: 120_000 });
  check(await page.getByRole("heading", { name: /entrevista de prueba ñandú/ }).isVisible(), "archivo con tildes y espacios cargado");
  await page.screenshot({ path: join(out, "02-cargado.png") });

  await page.getByRole("button", { name: "Probar este fragmento" }).click();
  await page.getByLabel("Compensar volumen al comparar").waitFor({ timeout: 180_000 });
  await page.waitForFunction(() => [...document.querySelectorAll("audio")].every((a) => a.readyState >= 2), null, { timeout: 30_000 });
  const durations = await page.$$eval("audio", (els) => els.map((a) => a.duration));
  check(durations.every((d) => Math.abs(d - 10) < 0.2), `ambos audios de vista previa duran ~10 s (${durations.map((d) => d.toFixed(2)).join(", ")})`);
  await page.screenshot({ path: join(out, "03-vista-previa.png"), fullPage: true });

  await page.getByRole("button", { name: /^Reproducir$/ }).click();
  await page.waitForTimeout(1200);
  const t1 = await page.$eval("audio:nth-of-type(2)", (a) => a.currentTime).catch(() => 0);
  await page.getByRole("button", { name: /^Original/ }).click();
  const pressed = await page.getByRole("button", { name: /^Original/ }).getAttribute("aria-pressed");
  check(pressed === "true", "alternar A/B marca el Original");
  const t2 = await page.$$eval("audio", (els) => els[0].currentTime);
  check(Math.abs(t2 - t1) < 0.5, `la posición se conserva al alternar (${t1.toFixed(2)} → ${t2.toFixed(2)})`);
  await page.getByRole("button", { name: /^Pausa$/ }).click();

  // Mover la posición de reproducción dentro del fragmento (seek): depende de peticiones con rango en el servidor
  const seek = page.getByRole("slider", { name: "Posición dentro del fragmento" });
  await seek.fill("6");
  await page.waitForTimeout(300);
  const seeked = await page.$$eval("audio", (els) => els.map((a) => a.currentTime));
  check(seeked.every((t) => Math.abs(t - 6) < 0.3), `la barra de posición mueve los dos audios (${seeked.map((t) => t.toFixed(2)).join(", ")})`);
  check(await page.getByText("0:06 / 0:10").isVisible(), "se muestra el tiempo dentro del fragmento");
  await page.screenshot({ path: join(out, "04-reproductor.png"), fullPage: true });

  // Pestaña Cadena: seleccionar una caja, cambiar parámetros y reordenar
  await page.getByRole("tab", { name: "Cadena" }).click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(out, "05-cadena.png"), fullPage: true });
  const names = async () => page.$$eval(".chain .box-name", (els) => els.map((e) => e.textContent));
  check(JSON.stringify(await names()) === JSON.stringify(["Entrada", "Recorte de graves", "DeepFilterNet3", "Volumen", "Salida"]), "la cadena por defecto: Entrada → graves → DeepFilterNet3 → Volumen → Salida");
  await page.locator('[data-box]', { hasText: "DeepFilterNet3" }).click();
  await page.getByRole("button", { name: "Mover antes" }).click();
  check(JSON.stringify(await names()) === JSON.stringify(["Entrada", "DeepFilterNet3", "Recorte de graves", "Volumen", "Salida"]), "«Mover antes» reordena las cajas");
  await page.getByLabel(/^Intensidad/).fill("60");
  check(await page.getByText(/Intensidad: 60 %/).isVisible(), "la configuración por caja cambia solo esa caja");
  await page.screenshot({ path: join(out, "06-cadena-reordenada.png"), fullPage: true });

  // Volver a Audio: la prueba ya no corresponde a la cadena actual
  await page.getByRole("tab", { name: "Audio" }).click();
  check(await page.getByText("Prueba desactualizada").isVisible(), "tras cambiar la cadena la prueba se marca desactualizada");
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(out, "07-desactualizada.png"), fullPage: true });
  await page.getByRole("button", { name: "Probar de nuevo" }).click();
  await page.getByText("Prueba desactualizada").waitFor({ state: "detached", timeout: 180_000 });
  check(true, "«Probar de nuevo» rehace la prueba con la cadena actual");

  await page.getByRole("tab", { name: "Cadena" }).click();
  await page.locator(".presets select").selectOption("builtin:exterior");
  check(JSON.stringify(await names()) === JSON.stringify(["Entrada", "Recorte de graves", "DeepFilterNet3", "Volumen", "Salida"]), "el preajuste reemplaza la cadena");
  await page.locator('[data-box]', { hasText: "Recorte de graves" }).click();
  check(await page.getByText(/Frecuencia de corte: 120 Hz/).isVisible(), "el preajuste cambia los parámetros de la caja");
  await page.getByRole("tab", { name: "Audio" }).click();

  await page.getByRole("button", { name: "Procesar todo el audio…" }).first().click();
  await page.getByText("Listo. Archivo guardado:").waitFor({ timeout: 300_000 });
  const saved = join(work, "salidas", "entrevista de prueba ñandú_mejorado.wav");
  check(existsSync(saved) && statSync(saved).size > 1_000_000, "el archivo final se escribió");
  check(await page.getByText(/Volumen:/).isVisible(), "se muestra el volumen antes → después");
  await page.screenshot({ path: join(out, "08-terminado.png"), fullPage: true });

  await page.setViewportSize({ width: 700, height: 900 });
  await page.screenshot({ path: join(out, "09-estrecho.png"), fullPage: true });
  await page.getByRole("tab", { name: "Cadena" }).click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(out, "09b-estrecho-cadena.png"), fullPage: true });
  await page.getByRole("tab", { name: "Audio" }).click();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.screenshot({ path: join(out, "10-oscuro.png"), fullPage: true });
  await page.getByRole("tab", { name: "Cadena" }).click();
  await page.waitForTimeout(300);
  await page.screenshot({ path: join(out, "10b-oscuro-cadena.png"), fullPage: true });
  await page.getByRole("tab", { name: "Audio" }).click();
  await page.emulateMedia({ colorScheme: "light" });

  // Error legible: archivo que no existe
  bridge.setOpenPath(join(work, "no existe.wav"));
  await page.getByRole("button", { name: /Abrir archivo/ }).click();
  await page.getByRole("alert").first().waitFor({ timeout: 30_000 });
  const alertText = await page.getByRole("alert").first().innerText();
  check(/No se pudo leer/.test(alertText), `error legible al abrir un archivo inexistente: «${alertText.split("\n")[0].slice(0, 60)}…»`);
  await page.screenshot({ path: join(out, "11-error.png") });
  check(pageErrors.length === 0, `sin errores en la consola del navegador ${pageErrors.length ? JSON.stringify(pageErrors) : ""}`);

  // --- Escenario 2: primer uso sin el modelo instalado (descarga real, verificada por sha256) ---
  const bridge2 = await startBridge({
    engineDir: join(app, "engine"), cacheDir: join(work, "cache2"), workDir: join(work, "engine-work2"),
    openPath: sample, saveDir: join(work, "salidas"), port: 4800,
    env: { AUDIO_ENHANCER_MODELS_DIR: join(work, "modelos-vacios") },
  });
  try {
    const page2 = await browser.newPage({ viewport: { width: 1280, height: 700 } });
    await page2.addInitScript(() => { globalThis.__BRIDGE__ = "http://127.0.0.1:4800"; });
    await page2.goto("http://localhost:1421");
    await page2.getByText(/modelo de reducción de ruido/).waitFor({ timeout: 60_000 });
    check(true, "sin modelo instalado se avisa claramente");
    await page2.screenshot({ path: join(out, "12-modelo-ausente.png") });
    await page2.getByRole("button", { name: "Descargar modelo ahora" }).click();
    await page2.getByText(/modelo de reducción de ruido/).waitFor({ state: "detached", timeout: 120_000 });
    check(existsSync(join(work, "modelos-vacios", "deepfilternet3", "enc.onnx")), "el modelo se descargó, verificó e instaló");
    // Pantalla de modelos: catálogo real desde el motor
    await page2.getByRole("tab", { name: "Modelos" }).click();
    await page2.getByRole("tabpanel", { name: "Modelos" }).getByText("Kim Vocal 2 (aislar voz)").waitFor({ timeout: 30_000 });
    check(await page2.getByText("Licencia sin verificar").count() >= 1, "el catálogo muestra la licencia sin verificar de Kim Vocal 2");
    check(await page2.getByRole("button", { name: "Quitar" }).count() === 1, "DeepFilterNet3 aparece instalado y Kim Vocal 2 no");
    await page2.getByRole("button", { name: "Instalar" }).click();
    await page2.getByRole("alertdialog").waitFor();
    check(!existsSync(join(work, "modelos-vacios", "kim-vocal-2")), "sin confirmar, el modelo no se descarga");
    await page2.screenshot({ path: join(out, "13-modelos.png"), fullPage: true });
  } finally {
    bridge2.close();
  }
} catch (e) {
  failures.push(String(e));
  console.error(e);
} finally {
  await browser.close();
  vite.kill();
  bridge.close();
}
console.log(`\nCapturas en ${out}`);
process.exit(failures.length ? 1 : 0);
