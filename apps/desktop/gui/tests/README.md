# Ürün akışı integration QA

`product-flow.cjs`, görünmez offscreen Electron penceresinde kaynak UI'ı ve gerçek preload/IPC route policy'yi kullanır. Kimlik oturumu yalnız bu test harness'ında sentetiktir; gerçek OAuth veya paketli uygulama kabulü anlamına gelmez. Product API, SQLite kalıcılığı ve Windows Türkçe TTS gerçektir. Ses çıkışı test sırasında sessizdir.

Windows'ta masaüstü Python `.venv`, GUI pnpm bağımlılıkları ve kurulu Türkçe Windows sesi gerekir. Repo kökünden:

```powershell
Start-Process -FilePath apps/desktop/gui/node_modules/electron/dist/electron.exe -ArgumentList apps/desktop/gui/tests/product-flow.cjs -WindowStyle Hidden -Wait
```

Her çalıştırma `.local/urun/ui-integration-<timestamp>` altında ayrı sentetik DB, makbuz ve PNG oluşturur. Kullanıcı DB'si, mevcut hesap ve modeller kullanılmaz. Test açılış kilidini, giriş sonrası haber özeti ve oynatılabilir WAV'ı, iki turlu kaynaklı araştırmayı, reload sonrası konuşma geçmişini ve çıkışla veri temizlenmesini doğrular. Makbuzdaki `ok` ve tüm `checks[].passed` alanları kontrol edilir. Bu klasör Electron paketinin `files` allowlist'inde değildir.

Ek sentetik arşiv, tamamlanmış 55 araştırma turu içerir. UI önce son 50 turu (100 mesaj), “Önceki mesajları yükle” ile kalan 5 turu açmalıdır. Test, 110 mesajın sırasını, gerçek cursor API isteğini ve geçmiş konuşma açıldığında çalışma alanı seçiminin kilitlenmesini de doğrular. Arşiv yanıtları test verisidir; model üretimi olarak değerlendirilmez.
