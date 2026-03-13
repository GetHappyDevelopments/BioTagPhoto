# Contributing to BioTagPhoto

Thank you for contributing to BioTagPhoto.

This document keeps contributions consistent, reviewable, and safe for a desktop application that works with local image libraries, face assignments, and optional third-party models.

## Scope

BioTagPhoto is a local desktop application built with:

- Python
- PySide6
- SQLite
- OpenCV
- optional InsightFace-based face analysis

Please keep changes focused. Small, isolated pull requests are easier to review and safer to merge.

## Before You Start

1. Read `README.md`, `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES.md`.
2. Do not add pretrained model files to the repository.
3. Do not commit personal databases, backups, generated build folders, or local test image collections.
4. If your change affects privacy, legal notices, backups, metadata writing, or face processing, mention that explicitly in the pull request.

## Development Setup

Use a local virtual environment in the project root:

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

If you work on release packaging:

```powershell
.\tools\build_release.ps1 -SkipInstaller
```

## Repository Rules

- Main branch: `main`
- Default remote: `origin`
- Keep commits logically separated.
- Prefer descriptive commit messages.
- Avoid force-pushing shared history unless this was explicitly coordinated.

Recommended commit style:

- `Add metadata dialog for person photos`
- `Fix SQLite path handling for installed builds`
- `Refactor unknown page selection handling`

## Code Style

- Prefer clear, direct Python over clever abstractions.
- Keep UI code in `ui/` and database logic in `db.py` or dedicated storage modules.
- Avoid introducing global mutable state when local state or dependency injection is sufficient.
- Keep typing clean and Pylance-friendly.
- Prefer ASCII unless the file already uses non-ASCII content.
- Add comments only where they explain non-obvious logic.

## Database and Migrations

If you change the schema:

- keep migrations idempotent
- preserve existing user data where possible
- ensure `init_db()` / `ensure_schema()` still work on both fresh and existing databases
- test against an existing database, not only an empty one

Never commit local runtime databases such as:

- `biotagphoto.db`
- files in `data/`
- exported backup files like `*.btp`

## Models and Licensing

BioTagPhoto does not ship the `buffalo_l` model pack.

Contributors must not:

- add pretrained InsightFace model weights to the repository
- hardcode private local model paths
- assume that model redistribution is allowed

If your change touches model loading or embedding generation, document the licensing and runtime implications in the pull request.

## UI Changes

For UI changes, include:

- what screen was changed
- what user workflow improved or changed
- screenshots if the layout changed visibly
- notes about keyboard shortcuts, dialogs, or long-running tasks if relevant

Avoid UI freezes. Long-running work should stay off the main thread or provide visible progress feedback.

## Testing

Before opening a pull request, run at least the checks that match your change.

Minimum checks:

```powershell
python -m compileall -q .
```

Useful targeted checks:

```powershell
python -m py_compile main.py db.py ui\main_window.py
python tools\sanity_check.py
```

If you cannot run a relevant check, say so clearly in the pull request.

## Pull Requests

Each pull request should include:

1. Summary of the change
2. Why the change is needed
3. Risks or side effects
4. How it was tested
5. Any follow-up work that remains open

Good pull requests are narrow and explicit. If a change touches multiple areas, explain the boundaries clearly.

## Security and Privacy

Be careful with:

- face embeddings
- image metadata writing
- export/import of local databases
- path handling on installed builds
- personally identifiable information in screenshots, fixtures, or logs

Do not include private user photos, private databases, or credentials in issues or pull requests.

## Questions

If you are unsure whether a change belongs in the repository, open an issue or draft pull request first and describe the intended direction before making the change large.
