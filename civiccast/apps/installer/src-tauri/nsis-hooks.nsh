; Tauri's reinstall page runs before the normal install hook. Repair an
; orphaned current-user uninstall registration here so a missing uninstaller
; cannot produce a false "Already Installed" page. Preserve a live install:
; both the registry's raw quoted path and its quote-trimmed form must be absent
; before cleanup is allowed.
!define MUI_CUSTOMFUNCTION_GUIINIT CivicCastRepairOrphanedUninstall
Function CivicCastRepairOrphanedUninstall
  SetRegView 64
  StrCpy $R0 ""
  ReadRegStr $R0 HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CivicCast Installer" "UninstallString"
  ${If} $R0 != ""
    StrCpy $R1 $R0 "" 1
    StrCpy $R1 $R1 -1
    ${IfNot} ${FileExists} "$R0"
      ${IfNot} ${FileExists} "$R1"
        DetailPrint "Removing orphaned CivicCast uninstall registration..."
        DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\CivicCast Installer"
        DeleteRegKey HKCU "Software\civiccast\CivicCast Installer"
        DeleteRegKey /ifempty HKCU "Software\civiccast"
      ${EndIf}
    ${EndIf}
  ${EndIf}
FunctionEnd

!macro NSIS_HOOK_PREINSTALL
  ; The GUI and its hidden runtime host share the same executable. Tauri's
  ; built-in running-app check occurs immediately after this hook and cannot
  ; reliably stop a process launched from a packaged desktop context because
  ; its shutdown marker may be virtualized into a different LocalCache. Stop
  ; the current-user CivicCast process tree before that check so repair and
  ; upgrade can replace the executable without an abort/retry loop.
  DetailPrint "Stopping the existing CivicCast app before installation..."
  nsExec::ExecToLog 'taskkill.exe /IM "civiccast-installer.exe" /T /F'
  Sleep 1500
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "Closing CivicCast Installer before uninstall..."
  FileOpen $1 "$INSTDIR\shutdown-request" w
  FileWrite $1 "uninstall"
  FileClose $1
  CreateDirectory "$PROFILE\.civiccast"
  FileOpen $3 "$PROFILE\.civiccast\shutdown-request" w
  FileWrite $3 "uninstall"
  FileClose $3
  Sleep 1500
  System::Call 'user32::FindWindowW(w "Tauri Window", w "CivicCast Installer") p.r0'
  ${If} $0 P<> 0
    System::Call 'user32::PostMessageW(p r0, i 0x0010, p 0, p 0) i.r1'
    Sleep 3000
  ${EndIf}
  nsExec::ExecToLog 'taskkill /IM "civiccast-installer.exe" /F'
  Sleep 1500
!macroend

!macro NSIS_HOOK_POSTINSTALL
  ; PE-ENG-3: headless-bootstrap.ps1 can legitimately run for up to ~2h. NSIS
  ; Exec launches it asynchronously, so the wizard can finish while the Tauri
  ; app reports real progress from installer-state.json. Keep every path in
  ; this one native command line: nested PowerShell process launchers flatten
  ; argument arrays and break the default "CivicCast Installer" path.
  DetailPrint "Starting CivicCast headless setup in the background..."
  Exec 'powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "$INSTDIR\resources\headless-bootstrap.ps1" -InstallDir "$INSTDIR"'
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  DetailPrint "Removing CivicCast autostart entry..."
  ; Current autostart mechanism: per-user HKCU Run value (no admin needed).
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "CivicCast Autostart"
  ; Legacy cleanup: earlier builds attempted an ONLOGON scheduled task.
  nsExec::ExecToLog 'schtasks.exe /Delete /TN "CivicCast Autostart" /F'

  ; rc13 lifecycle repair: Tauri/NSIS uses this InstallDirRegKey to decide
  ; whether an older version is present. Leaving it behind after uninstall
  ; produces a false "Already Installed" page on an otherwise clean host.
  DeleteRegKey HKCU "Software\civiccast\CivicCast Installer"
  DeleteRegKey /ifempty HKCU "Software\civiccast"

  ; F-RC3-8 (clean-VM gauntlet): rc3's uninstall reported success while the
  ; WSL station kept running and serving :8000, and the distro + all data
  ; survived even with "Delete the application data" checked. Always STOP the
  ; runtime so no service outlives its uninstaller; remove the distro and the
  ; CivicCast data dirs only when the operator checked delete-app-data.
  ; wsl.exe note: the uninstaller can run as a 32-bit process, where System32
  ; is redirected to SysWOW64 (no wsl.exe) — prefer Sysnative when it exists.
  DetailPrint "Stopping the CivicCast Windows helper runtime..."
  nsExec::ExecToLog 'cmd.exe /c "if exist %WINDIR%\Sysnative\wsl.exe (%WINDIR%\Sysnative\wsl.exe --terminate CivicCast-Ubuntu-24.04) else (wsl.exe --terminate CivicCast-Ubuntu-24.04)"'
  ${If} $DeleteAppDataCheckboxState = 1
    DetailPrint "Removing the CivicCast helper runtime and station data..."
    nsExec::ExecToLog 'cmd.exe /c "if exist %WINDIR%\Sysnative\wsl.exe (%WINDIR%\Sysnative\wsl.exe --unregister CivicCast-Ubuntu-24.04) else (wsl.exe --unregister CivicCast-Ubuntu-24.04)"'
    RMDir /r /REBOOTOK "$PROFILE\.civiccast"
    RMDir /r /REBOOTOK "$PROFILE\AppData\Local\CivicCast"
    RMDir /r /REBOOTOK "$INSTDIR"
  ${Else}
    ; F-RC4-1: the base NSIS uninstaller self-deletes, so telling the operator
    ; to "rerun the uninstaller with the box checked" is a dead end — there is
    ; no uninstaller left. Give a path that does not need it: the two commands
    ; that remove what "keep application data" left behind (the WSL distro that
    ; holds the recordings/database, and the CivicCast state folder).
    DetailPrint "Application data kept. CivicCast's recordings and database stay in the Windows helper (WSL distro CivicCast-Ubuntu-24.04), and installer state stays in %USERPROFILE%\.civiccast. To remove them later, ask IT to run: wsl --unregister CivicCast-Ubuntu-24.04  and delete the %USERPROFILE%\.civiccast folder. (Reinstalling and uninstalling again with 'Delete the application data' checked also removes them.)"

    ; rc17 F-5: NSIS_HOOK_PREUNINSTALL writes a shutdown-request marker to
    ; close the running app. The delete path removes $INSTDIR wholesale, but
    ; nothing cleaned it on the keep path, so an otherwise-empty CivicCast
    ; program folder survived an uninstall the operator watched succeed.
    ; RMDir without /r deletes the folder only when it is empty, so a genuine
    ; leftover is preserved for diagnosis rather than silently destroyed.
    Delete "$INSTDIR\shutdown-request"
    RMDir "$INSTDIR"
    ; The .civiccast copy is deliberately kept state, but the marker inside it
    ; is transient. The app clears stale markers at startup, so this is tidiness
    ; rather than a fix -- it just stops an "uninstall" marker outliving the
    ; uninstall in a folder we tell the operator to keep.
    Delete "$PROFILE\.civiccast\shutdown-request"

    ; rc17: DetailPrint has no window to draw in during a silent (/S) uninstall,
    ; so a scripted removal finished with no indication that the recordings and
    ; database -- roughly 19 GB -- were kept. Leave the same wording on disk
    ; where an operator or a script can read it afterwards. This path keeps
    ; .civiccast by definition, so it is a safe place to write.
    CreateDirectory "$PROFILE\.civiccast"
    FileOpen $4 "$PROFILE\.civiccast\uninstall.log" w
    FileWrite $4 "CivicCast was uninstalled and the application data was KEPT.$\r$\n"
    FileWrite $4 "Recordings and database: Windows helper (WSL distro CivicCast-Ubuntu-24.04).$\r$\n"
    FileWrite $4 "Installer state: %USERPROFILE%\.civiccast$\r$\n"
    FileWrite $4 "To remove them later, run: wsl --unregister CivicCast-Ubuntu-24.04$\r$\n"
    FileWrite $4 "then delete the %USERPROFILE%\.civiccast folder.$\r$\n"
    FileWrite $4 "(Reinstalling and uninstalling again with 'Delete the application data' checked also removes them.)$\r$\n"
    FileClose $4
  ${EndIf}
!macroend
