# GitHub releases

The repository includes an automated Windows build workflow at `.github/workflows/windows-release.yml`.

A pushed version tag such as `v0.1.3` triggers a Windows build and creates a GitHub Release containing:

- `956A_Generator_Setup.exe` - normal per-user Windows installer
- `956A_Generator_Setup.exe.sha256` - installer checksum
- `956A_Generator_Windows_Portable.zip` - no-install fallback
- `956A_Generator_Windows_Portable.zip.sha256` - portable checksum
- `instructions.txt` - Windows staff instructions

The installer uses `%LOCALAPPDATA%\Programs\956A Generator` and therefore does not normally require administrator rights.
