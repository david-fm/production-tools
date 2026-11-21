//! Shell de Tauri: arranca y supervisa el motor de audio (sidecar Python) por stdio.
//!
//! Contrato: una petición JSON por línea en stdin, una respuesta/evento JSON por línea en stdout.
//! Ver `engine/README.md`. Responsabilidades de este módulo:
//! - arrancar el motor y reiniciarlo si muere o deja de responder (heartbeat);
//! - correlacionar respuestas por `id`;
//! - reenviar eventos de progreso a la interfaz;
//! - terminar el motor (y TODO su árbol de procesos) al cerrar la app o al reiniciarlo.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{json, Map, Value};
use tauri::{AppHandle, Emitter, Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::oneshot;

const HEARTBEAT_EVERY: Duration = Duration::from_secs(5);
const HEARTBEAT_TIMEOUT: Duration = Duration::from_secs(5);
/// Un motor `--onefile` en frío (extracción + antivirus) puede tardar en responder el primer `ping`.
const STARTUP_GRACE: Duration = Duration::from_secs(60);
/// Fallos de latido consecutivos antes de reiniciar el motor.
const HEARTBEAT_MAX_MISSES: u32 = 2;
const CALL_TIMEOUT: Duration = Duration::from_secs(30);

type Pending = HashMap<u64, oneshot::Sender<Result<Value, String>>>;

#[derive(Default)]
struct Inner {
    child: Option<CommandChild>,
    pid: Option<u32>,
    pending: Pending,
    /// Se incrementa en cada arranque; evita que un motor viejo cierre el estado del nuevo.
    generation: u64,
    /// Generación del motor vivo (None si no hay ninguno). Hace idempotente `on_engine_gone`.
    alive_generation: Option<u64>,
    /// El motor de esta generación ya respondió a un `ping`.
    ready: bool,
    shutting_down: bool,
}

#[derive(Clone, Default)]
pub struct Engine {
    inner: Arc<Mutex<Inner>>,
    next_id: Arc<AtomicU64>,
}

/// Construye la petición. `id` y `cmd` se fijan DESPUÉS de los params: la interfaz no puede
/// pisarlos (si lo hiciera, la respuesta no coincidiría con la llamada pendiente).
fn build_request(id: u64, cmd: &str, params: &Value) -> Value {
    let mut obj = Map::new();
    if let Some(extra) = params.as_object() {
        for (k, v) in extra {
            obj.insert(k.clone(), v.clone());
        }
    }
    obj.insert("id".into(), json!(id));
    obj.insert("cmd".into(), json!(cmd));
    Value::Object(obj)
}

/// Mata un proceso y todos sus descendientes. `--onefile` de PyInstaller crea dos procesos
/// (bootloader + intérprete) y matar solo al padre dejaría al hijo vivo.
fn kill_process_tree(pid: u32) {
    #[cfg(windows)]
    {
        let _ = std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .output();
    }
    #[cfg(unix)]
    {
        // Descendientes primero (pkill -P solo alcanza a los hijos directos; se recorre el árbol).
        fn descendants(pid: u32, out: &mut Vec<u32>) {
            if let Ok(res) = std::process::Command::new("pgrep").args(["-P", &pid.to_string()]).output() {
                for line in String::from_utf8_lossy(&res.stdout).lines() {
                    if let Ok(child) = line.trim().parse::<u32>() {
                        out.push(child);
                        descendants(child, out);
                    }
                }
            }
        }
        let mut all = Vec::new();
        descendants(pid, &mut all);
        all.push(pid);
        for p in all.into_iter().rev() {
            let _ = std::process::Command::new("kill").args(["-KILL", &p.to_string()]).output();
        }
    }
}

impl Engine {
    /// Arranca el sidecar y lanza la tarea que lee su stdout. No hace nada si la app se está cerrando.
    fn spawn(&self, app: &AppHandle) -> Result<(), String> {
        if self.inner.lock().unwrap().shutting_down {
            return Ok(());
        }
        let (mut rx, child) = app
            .shell()
            .sidecar("audio-enhancer-engine")
            .map_err(|e| format!("no se encontró el motor: {e}"))?
            .spawn()
            .map_err(|e| format!("no se pudo iniciar el motor: {e}"))?;

        let generation = {
            let mut inner = self.inner.lock().unwrap();
            if inner.shutting_down {
                // El cierre empezó mientras arrancábamos: este motor nadie lo mataría después.
                kill_process_tree(child.pid());
                let _ = child.kill();
                return Ok(());
            }
            inner.generation += 1;
            inner.pid = Some(child.pid());
            inner.child = Some(child);
            inner.alive_generation = Some(inner.generation);
            inner.ready = false;
            inner.generation
        };

        let engine = self.clone();
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            while let Some(event) = rx.recv().await {
                match event {
                    CommandEvent::Stdout(bytes) => {
                        let line = String::from_utf8_lossy(&bytes);
                        let Ok(msg) = serde_json::from_str::<Value>(line.trim()) else {
                            continue; // línea que no es JSON: se ignora
                        };
                        engine.dispatch(&app, msg);
                    }
                    CommandEvent::Stderr(bytes) => {
                        eprintln!("[motor] {}", String::from_utf8_lossy(&bytes).trim_end());
                    }
                    CommandEvent::Terminated(_) | CommandEvent::Error(_) => break,
                    _ => {}
                }
            }
            engine.on_engine_gone(&app, generation);
        });
        Ok(())
    }

    fn dispatch(&self, app: &AppHandle, msg: Value) {
        if msg.get("event").and_then(Value::as_str) == Some("progress") {
            let _ = app.emit("engine-progress", &msg);
            return;
        }
        let Some(id) = msg.get("id").and_then(Value::as_u64) else { return };
        let tx = self.inner.lock().unwrap().pending.remove(&id);
        if let Some(tx) = tx {
            let result = if msg.get("ok").and_then(Value::as_bool) == Some(true) {
                Ok(msg.get("result").cloned().unwrap_or(Value::Null))
            } else {
                Err(msg.get("error").and_then(Value::as_str).unwrap_or("error desconocido").to_string())
            };
            let _ = tx.send(result);
        }
    }

    /// El motor de `generation` terminó o se declaró muerto. Idempotente: puede llamarse desde el
    /// lector de stdout y desde el heartbeat sin provocar un doble reinicio.
    fn on_engine_gone(&self, app: &AppHandle, generation: u64) {
        let restart = {
            let mut inner = self.inner.lock().unwrap();
            if inner.alive_generation != Some(generation) {
                return; // ya gestionado, o hay un motor más nuevo
            }
            inner.alive_generation = None;
            inner.ready = false;
            let pid = inner.pid.take();
            let child = inner.child.take();
            // Si el proceso siguiera vivo (p. ej. error de lectura), se elimina todo su árbol.
            if let Some(pid) = pid {
                kill_process_tree(pid);
            }
            if let Some(child) = child {
                let _ = child.kill();
            }
            for (_, tx) in inner.pending.drain() {
                let _ = tx.send(Err("el motor de audio se detuvo".into()));
            }
            !inner.shutting_down
        };
        if restart {
            let engine = self.clone();
            let app = app.clone();
            tauri::async_runtime::spawn(async move {
                tokio::time::sleep(Duration::from_millis(500)).await;
                if let Err(e) = engine.spawn(&app) {
                    eprintln!("[shell] reinicio del motor falló: {e}");
                }
            });
        }
    }

    fn write_line(&self, value: &Value) -> Result<(), String> {
        let mut inner = self.inner.lock().unwrap();
        let child = inner.child.as_mut().ok_or("el motor no está en ejecución")?;
        child
            .write(format!("{value}\n").as_bytes())
            .map_err(|e| format!("no se pudo escribir al motor: {e}"))
    }

    pub async fn call(&self, cmd: &str, params: Value, timeout: Duration) -> Result<Value, String> {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst) + 1;
        let (tx, rx) = oneshot::channel();
        self.inner.lock().unwrap().pending.insert(id, tx);

        if let Err(e) = self.write_line(&build_request(id, cmd, &params)) {
            self.inner.lock().unwrap().pending.remove(&id);
            return Err(e);
        }
        match tokio::time::timeout(timeout, rx).await {
            Ok(Ok(result)) => result,
            Ok(Err(_)) => Err("el motor de audio se detuvo".into()),
            Err(_) => {
                self.inner.lock().unwrap().pending.remove(&id);
                Err("el motor de audio no respondió a tiempo".into())
            }
        }
    }

    /// Cierre de la app: pide `shutdown`, y mata el árbol de procesos. Idempotente.
    fn shutdown(&self) {
        let (pid, child) = {
            let mut inner = self.inner.lock().unwrap();
            if inner.shutting_down {
                return;
            }
            inner.shutting_down = true;
            inner.alive_generation = None;
            if let Some(child) = inner.child.as_mut() {
                let _ = child.write(b"{\"id\":0,\"cmd\":\"shutdown\"}\n");
            }
            (inner.pid.take(), inner.child.take())
        };
        std::thread::sleep(Duration::from_millis(200));
        if let Some(pid) = pid {
            kill_process_tree(pid);
        }
        if let Some(child) = child {
            let _ = child.kill();
        }
    }

    async fn heartbeat_loop(self, app: AppHandle) {
        let mut misses = 0u32;
        let mut started_at = tokio::time::Instant::now();
        let mut last_generation = 0u64;
        loop {
            tokio::time::sleep(HEARTBEAT_EVERY).await;
            let (generation, alive, ready, shutting_down) = {
                let inner = self.inner.lock().unwrap();
                (inner.generation, inner.alive_generation, inner.ready, inner.shutting_down)
            };
            if shutting_down {
                return;
            }
            if generation != last_generation {
                last_generation = generation;
                started_at = tokio::time::Instant::now();
                misses = 0;
            }
            if alive != Some(generation) {
                continue; // reiniciándose
            }
            match self.call("ping", json!({}), HEARTBEAT_TIMEOUT).await {
                Ok(_) => {
                    misses = 0;
                    self.inner.lock().unwrap().ready = true;
                }
                // Durante el arranque en frío el motor puede tardar: se da un margen largo.
                Err(_) if !ready && started_at.elapsed() < STARTUP_GRACE => {}
                Err(_) => {
                    misses += 1;
                    if misses >= HEARTBEAT_MAX_MISSES {
                        eprintln!("[shell] el motor no responde al heartbeat; se reinicia");
                        misses = 0;
                        // No depende de que llegue `Terminated`: se declara muerto y se reinicia.
                        self.on_engine_gone(&app, generation);
                    }
                }
            }
        }
    }
}

#[tauri::command]
async fn engine_call(
    engine: tauri::State<'_, Engine>,
    cmd: String,
    params: Option<Value>,
    timeout_s: Option<u64>,
) -> Result<Value, String> {
    // Los trabajos largos (procesar horas de audio) pasan un límite grande: su avance se ve por eventos.
    let timeout = timeout_s.map(Duration::from_secs).unwrap_or(CALL_TIMEOUT);
    engine.call(&cmd, params.unwrap_or(Value::Null), timeout).await
}

pub fn run() {
    let engine = Engine::default();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(engine.clone())
        .invoke_handler(tauri::generate_handler![engine_call])
        .setup(|app| {
            let engine = app.state::<Engine>().inner().clone();
            engine.spawn(app.handle())?;
            tauri::async_runtime::spawn(engine.heartbeat_loop(app.handle().clone()));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error al construir la aplicación");

    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit) {
            handle.state::<Engine>().shutdown();
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn params_cannot_override_id_or_cmd() {
        let req = build_request(7, "health", &json!({"id": 99, "cmd": "shutdown", "steps": 3}));
        assert_eq!(req["id"], 7);
        assert_eq!(req["cmd"], "health");
        assert_eq!(req["steps"], 3);
    }

    #[test]
    fn null_params_are_accepted() {
        let req = build_request(1, "ping", &Value::Null);
        assert_eq!(req, json!({"id": 1, "cmd": "ping"}));
    }

    #[cfg(unix)]
    #[test]
    fn kill_process_tree_kills_grandchildren() {
        use std::process::{Command, Stdio};
        // sh -> sleep (nieto del test): matar solo a sh dejaría vivo a sleep.
        let mut parent = Command::new("sh")
            .args(["-c", "sleep 300 & wait"])
            .stdout(Stdio::null())
            .spawn()
            .unwrap();
        std::thread::sleep(Duration::from_millis(300));
        let pid = parent.id();
        let kids = Command::new("pgrep").args(["-P", &pid.to_string()]).output().unwrap();
        let grandchild: u32 = String::from_utf8_lossy(&kids.stdout).trim().parse().expect("hay un nieto");

        kill_process_tree(pid);
        let _ = parent.wait();
        std::thread::sleep(Duration::from_millis(200));

        let alive = Command::new("kill").args(["-0", &grandchild.to_string()]).output().unwrap();
        assert!(!alive.status.success(), "el proceso nieto sigue vivo");
    }
}
