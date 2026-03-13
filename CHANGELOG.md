# Changelog

All notable changes to this project should be documented in this file.

The format is based on Keep a Changelog and the project uses date-based release naming.

## [Unreleased]

### Added
- CONTRIBUTING guide for repository workflows and contribution expectations
- Privacy, legal, license, and first-run usage confirmation dialogs
- README screenshots and a clearer setup workflow
- `requirements-dev.txt` for development and release tooling

### Changed
- repository documentation and installation guidance were rewritten for fresh checkouts
- GitHub repository setup was aligned with `GetHappyDevelopments/BioTagPhoto`

### Fixed
- database reset now works reliably on Windows without deleting a locked SQLite file
- SQLite connections are now closed correctly after context-managed DB access
- database path migration support after project renaming

## [2026.02.01BETA]

### Added
- initial public beta release pipeline with PyInstaller and Inno Setup
- face review, assignment, metadata, backup, and embedding workflow foundation
