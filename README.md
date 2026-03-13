# BioTagPhoto

BioTagPhoto is a local desktop application for reviewing photos, detecting faces, assigning people, and writing selected person tags back to image metadata.

The application is built with:

- Python
- PySide6
- SQLite
- OpenCV
- optional InsightFace face analysis models

## Current Status

The repository contains the application source code, UI assets, release pipeline files, and legal/license documents required to build and run the project.

The InsightFace model pack `buffalo_l` is **not** included in this repository and is **not** distributed with the application.

## Screenshots

### Main Window

![BioTagPhoto Main Window](docs/screenshots/main-window.png)

### Settings Dialog

![BioTagPhoto Settings Dialog](docs/screenshots/settings-dialog.png)

## Features

- analyze configured source folders for faces
- manage unknown, suggested, and assigned faces
- review person pages and image metadata
- write selected person names into XMP metadata
- export and import local database backups
- build Windows releases with PyInstaller and Inno Setup

## Typical Workflow

1. Start the application.
2. Configure the InsightFace model path when prompted, or later via `Settings > Models`.
3. Add source folders in `Settings > Sources`.
4. Run `Analyze Images` from the `Unknown` screen.
5. Review unknown faces and assign them to existing or new people.
6. Open `People` to review grouped faces and manage metadata.
7. Optionally write person names back to XMP using `Tag Photo`.
8. Export a backup before major data changes.

## Requirements

- Windows recommended
- Python 3.10 or 3.11 recommended for best third-party wheel support
- a local virtual environment (`.venv`)
- separate installation of the InsightFace model pack if you want face analysis

## Setup

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start the application:

```powershell
python main.py
```

## Development Setup

For tests and release tooling:

```powershell
pip install -r requirements-dev.txt
```

Useful checks:

```powershell
python -m compileall -q .
python -m py_compile main.py db.py ui\main_window.py
python tools\sanity_check.py
```

## Model Setup

BioTagPhoto does not ship the `buffalo_l` model pack.

You must download and install it separately, then configure the model folder in the application.
On first start, BioTagPhoto will prompt for the folder if it is not configured yet.

Expected structure:

```text
<models-root>\buffalo_l\...
```

Typical location used by InsightFace:

```text
%USERPROFILE%\.insightface\models
```

## Release Build

Build only the application bundle:

```powershell
.\tools\build_release.ps1 -SkipInstaller
```

Build bundle and installer:

```powershell
.\tools\build_release.ps1
```

Expected outputs:

```text
dist\BioTagPhoto\BioTagPhoto.exe
release\BioTagPhoto_Setup_2026.02.01BETA.exe
```

## Repository Layout

```text
ui/              Qt UI pages, dialogs, workers, and jobs
packaging/       PyInstaller and Inno Setup configuration
tools/           helper scripts and sanity checks
docs/screenshots README screenshots
main.py          application entry point
db.py            SQLite schema and data access
```

## Legal and Licensing

Read these files before distribution or commercial use:

- `LICENSE`
- `NOTICE`
- `THIRD_PARTY_NOTICES.md`
- `PRIVACY.md`
- `LEGAL.md`

Important:
Third-party libraries and model files are subject to their own license terms. The source code license of BioTagPhoto does not automatically apply to external models.

## Contributing

See `CONTRIBUTING.md`.
