# Third-Party Notices

This document is a practical summary for BioTagPhoto distributions. It is not
legal advice and does not replace the original license texts of upstream
projects.

## Core runtime dependencies

- `PySide6`
  - Upstream: Qt for Python
  - License: `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`, or commercial Qt
    license
  - Impact: If you distribute BioTagPhoto with PySide6 under the community
    edition, you must comply with the applicable Qt open source terms.

- `numpy`
  - Upstream license: BSD-3-Clause
  - Impact: permissive, normally compatible with MIT-licensed application code

- `opencv-python` / OpenCV
  - Upstream license: Apache-2.0
  - Impact: permissive, normally compatible with MIT-licensed application code

- `onnxruntime`
  - Upstream license: MIT
  - Impact: permissive, normally compatible with MIT-licensed application code

- `Pillow`
  - Upstream license: HPND-style / Pillow license
  - Impact: permissive, normally compatible with MIT-licensed application code

- `insightface` source code
  - Upstream license: MIT
  - Impact: the source package itself is permissive

## Important model licensing note

The main legal risk for this project is not the Python package dependency
itself, but the pretrained face-recognition models used with InsightFace.

InsightFace states that pretrained models available through the project are
intended for non-commercial research purposes unless a separate commercial
license is obtained.

Practical consequence:

- You may publish the BioTagPhoto source code under MIT.
- You should not assume that this automatically permits commercial
  redistribution or commercial use of a build that ships with, downloads, or
  relies on restricted pretrained InsightFace models.

## Recommended distribution posture

For the current codebase, the safest public position is:

- BioTagPhoto source code: `MIT`
- Third-party libraries: under their original licenses
- Face-recognition models: under their original model terms

If you want a commercially clean release, replace the current pretrained
InsightFace models with models whose commercial redistribution and use are
explicitly permitted, or acquire the relevant commercial rights.
