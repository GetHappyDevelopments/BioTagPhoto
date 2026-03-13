MIT License

Copyright (c) 2026 Thomas Steier

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

BioTagPhoto
Copyright (c) 2026 Thomas Steier

The source code of this project is provided under the MIT License.

Important:
This project depends on third-party libraries and may download or use
third-party machine learning models. Those components are not relicensed under
the MIT License and remain subject to their own license terms.

In particular:
- PySide6 is distributed under LGPL/GPL/commercial terms from Qt.
- OpenCV, NumPy, ONNX Runtime and other dependencies are subject to their own
  upstream licenses.
- InsightFace source code is MIT licensed, but pretrained InsightFace models
  may be restricted to non-commercial research use unless a separate commercial
  license is obtained.

Anyone redistributing or commercially using BioTagPhoto is responsible for
reviewing and complying with all applicable third-party license obligations.


BioTagPhoto Legal Notice

License Position

The BioTagPhoto source code is provided under the MIT License unless stated otherwise.
Third-party libraries and model files remain subject to their own license terms.

Contact

Thomas Steier
Bertha-Benz-Karree 31
51107 Cologne
Germany
E-mail: BioTagPhoto@steier-familie.de

Model Notice

BioTagPhoto does not ship the InsightFace model pack `buffalo_l`.
If the user downloads and configures that model separately, the user is responsible for ensuring
that the model license allows the intended use case, including any commercial use.

Acceptable Use

This software is intended for lawful photo organization and review workflows.
It must not be used for unlawful surveillance, covert monitoring, unlawful employee tracking,
or any other use that violates privacy, employment, civil, criminal, or regulatory law.

Accuracy and Risk

Face detection, similarity scores, suggestions, and automatic assignments can be wrong.
Results must be reviewed by a human before being relied upon.

Do not use this software as the sole basis for:

- employment decisions
- disciplinary measures
- access control
- law-enforcement decisions
- immigration decisions
- medical or safety-critical decisions

No Warranty

The software is provided "as is", without warranties of any kind, express or implied,
including merchantability, fitness for a particular purpose, and non-infringement,
to the maximum extent permitted by applicable law.

Limitation of Liability

To the maximum extent permitted by law, the author shall not be liable for direct, indirect,
incidental, consequential, special, exemplary, or punitive damages arising from the use of,
or inability to use, the software.

User Responsibility

The user is responsible for:

- ensuring a valid legal basis for processing images and face data
- complying with privacy, employment, and copyright law
- checking third-party library and model licenses
- protecting local data, backups, and exported files
- validating assignments before writing metadata back to files

Before Distribution

Before public or commercial release, complete the following:

- review privacy notice wording with counsel if needed
- verify third-party license compliance
- verify model licensing separately from the application source code

No Legal Advice

This notice is provided for product documentation purposes and is not legal advice.

BioTagPhoto Privacy Notice

Controller / Responsible Party

Thomas Steier
BioTagPhoto
Bertha-Benz-Karree 31
51107 Cologne
Germany
E-mail: BioTagPhoto@steier-familie.de

What BioTagPhoto Processes

BioTagPhoto can process the following data on the local system:

- image file paths and configured source folders
- detected face regions within images
- person names entered by the user
- assignments between detected faces and persons
- face embeddings and person prototype embeddings
- local application settings, excluded items, and backup metadata
- optional image metadata shown in the UI, including EXIF, IPTC, and XMP data already present in image files

Purpose of Processing

The software is intended to help users:

- organize local image collections
- review unknown faces
- assign faces to named persons
- write selected name tags to image metadata
- export and import local database backups

Legal Basis

The user is responsible for ensuring that every use of this software has a valid legal basis.
Depending on the jurisdiction and use case, this may require consent, an employment agreement,
contractual necessity, a legitimate-interest assessment, or another specific legal basis.

Special Categories / Biometric Data

Face images and especially embeddings may qualify as biometric or otherwise sensitive personal data.
The user must verify whether stricter rules apply before processing such data.

Storage Location

By default, the local application database is stored on Windows under:

%LocalAppData%\BioTagPhoto\tagthatphoto.db

Additional settings are stored via platform settings storage used by Qt / QSettings.

Retention

Data remains stored until the user deletes or resets it.
The software currently does not enforce an automatic retention schedule.
Before productive use, define a retention concept that matches the intended deployment.

Sharing and Transfers

BioTagPhoto is designed as a local desktop application.
It does not intentionally upload face data to a cloud service by default.
However, users remain responsible for how source images, backups, and model files are obtained,
stored, copied, or shared.

Data Subject Rights

Depending on the applicable law, affected persons may have rights such as:

- access
- rectification
- deletion
- restriction of processing
- objection
- data portability
- complaint to a supervisory authority

The operator of the software, not the software itself, is responsible for handling these requests.

Operational Guidance

- only import images you are allowed to process
- define who may access the workstation and backups
- protect exported backup files
- remove data that is no longer needed
- document your legal basis and retention rules before production use

No Legal Advice

This notice is a technical template for the application UI and is not legal advice.
It should still be reviewed before public or commercial deployment.

