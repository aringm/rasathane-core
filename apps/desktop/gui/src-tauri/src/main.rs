#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;

#[cfg(windows)]
use std::process::Command;
#[cfg(windows)]
use std::os::windows::process::CommandExt;

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

// Sidecar child handle — GUI kapaninca OLDURMEK icin sakla. Aksi halde onefile sidecar
// oksuz kalir, port 8765'i tutar ve sonraki acilislari bozar (denetim HIGH).
struct SidecarChild(Mutex<Option<CommandChild>>);

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

fn sidecar_agacini_durdur(child: CommandChild) {
    #[cfg(windows)]
    {
        // PyInstaller --onefile bir bootstrap parent ve gerçek servis child'ı oluşturur.
        // Yalnız CommandChild::kill çağrısı parent'ı öldürüp HTTP child'ını yetim bırakabilir.
        let pid = child.pid().to_string();
        let sonuc = Command::new("taskkill")
            .args(["/PID", &pid, "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .status();
        if sonuc.is_ok_and(|durum| durum.success()) {
            return;
        }
    }

    let _ = child.kill();
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarChild(Mutex::new(None)))
        .setup(|app| {
            // Sidecar'i http modunda baslat (GUI -> 127.0.0.1:8765 -> core).
            let sidecar = app
                .shell()
                .sidecar("ytanaliz-sidecar")
                .expect("sidecar bulunamadi")
                .args(["http"]);
            let (mut rx, child) = sidecar.spawn().expect("sidecar spawn edilemedi");
            // Child handle'ini sakla (exit'te kill icin).
            app.state::<SidecarChild>().0.lock().unwrap().replace(child);
            tauri::async_runtime::spawn(async move {
                while let Some(ev) = rx.recv().await {
                    match ev {
                        CommandEvent::Stdout(line) => {
                            println!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        // stderr + olum olaylari ARTIK sessiz degil (denetim MED): port 8765
                        // catismasi / import hatasi gorunur olsun (sessiz sidecar olumu yok).
                        CommandEvent::Stderr(line) => {
                            eprintln!("[sidecar:err] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Error(err) => {
                            eprintln!("[sidecar:error] {}", err);
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!("[sidecar] sonlandi: {:?}", payload);
                        }
                        _ => {}
                    }
                }
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("tauri uygulamasi olusturulamadi")
        .run(|app_handle, event| {
            // GUI kapanirken sidecar'i oldur (take(): yalniz bir kez; port kilidini birak).
            if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
                if let Some(child) = app_handle.state::<SidecarChild>().0.lock().unwrap().take() {
                    sidecar_agacini_durdur(child);
                }
            }
        });
}
