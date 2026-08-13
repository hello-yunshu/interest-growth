; Interest Growth v0.5 supports Windows 11 24H2+ only.
; CurrentBuildNumber is numeric (26100 for Windows 11 24H2).
!macro NSIS_HOOK_PREINSTALL
  ReadRegStr $0 HKLM "SOFTWARE\Microsoft\Windows NT\CurrentVersion" "CurrentBuildNumber"
  IntCmp $0 26100 pg_windows_supported pg_windows_unsupported pg_windows_supported

  pg_windows_unsupported:
    MessageBox MB_ICONSTOP|MB_OK "Interest Growth requires Windows 11 24H2 or later (build 26100+)."
    Abort

  pg_windows_supported:
!macroend
