# BioTagPhoto Release Pipeline

This project is set up for a Windows desktop release pipeline based on
`PyInstaller` and `Inno Setup`.

## Prerequisites

- Windows
- Project virtual environment at `.venv`
- Inno Setup 6 installed

## Build a release

Run from the project root:

```powershell
.\tools\build_release.ps1
```

This performs two steps:

- builds a frozen application bundle with `PyInstaller`
- builds a Windows installer with `Inno Setup`

## Build only the application bundle

```powershell
.\tools\build_release.ps1 -SkipInstaller
```

The resulting executable bundle is expected at:

```text
dist\BioTagPhoto\BioTagPhoto.exe
```

The resulting installer is expected at:

```text
release\BioTagPhoto_Setup_2026.02.01BETA.exe
```

## Notes

- The current release pipeline packages the application code and bundled
  dependencies. Review third-party license obligations before distribution.
- If the application uses pretrained InsightFace models, review the model terms
  separately before shipping a public or commercial release.
- The release pipeline intentionally does not bundle the `buffalo_l` model pack.
  End users must install/download that model separately and then configure the
  model folder in the application.
- The SQLite database is stored under `%LocalAppData%\\BioTagPhoto` so the
  installed application does not need write access to the install directory.
- Qt settings are stored via the platform-specific `QSettings` backend.
