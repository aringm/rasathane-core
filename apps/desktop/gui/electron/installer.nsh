!include "LogicLib.nsh"

; Electron 43 checks that its sandbox token can read installed application assets.
; https://github.com/electron/electron/blob/v43.7.7/shell/browser/win/install_dir_access.cc
; Only the installed application tree receives inherited read/execute permission.
!macro customInstall
  Push $0
  Push $1
  nsExec::ExecToStack /TIMEOUT=30000 '"$SYSDIR\icacls.exe" "$INSTDIR" /grant "*S-1-15-2-1:(OI)(CI)(RX)"'
  Pop $0
  Pop $1
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "Rasathane uygulama klasörünün sandbox erişim izni ayarlanamadı. Kurulum durduruldu. Hata kodu: $0" /SD IDOK
    Pop $1
    Pop $0
    SetErrorLevel 1
    Abort "Sandbox erişim izni ayarlanamadığı için kurulum durduruldu."
  ${EndIf}
  Pop $1
  Pop $0
!macroend
