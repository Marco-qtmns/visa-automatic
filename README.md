# 956A Generator

> The existing Tkinter generator below remains available. Milestones 3 and 4 add
> a central-backend employee web client under [`frontend`](frontend/README.md);
> it is developed independently and does not replace the form filler. The
> backend's deterministic TRV requirement rules are documented in
> [`backend/REQUIREMENTS.md`](backend/REQUIREMENTS.md).

Local desktop prototype for generating Australian Department of Home Affairs Form 956A.

## Milestone 3 employee UI (development)

The browser UI coexists with the desktop generator. Start the backend and
frontend in separate terminals after copying the example environment files:

```bash
# terminal 1, from Programm/
export DATABASE_URL='postgresql+psycopg://user:password@localhost/visa_automatic'
alembic -c backend/alembic.ini upgrade head
uvicorn backend.app.main:app --reload

# terminal 2, from Programm/frontend/
cp .env.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000/cases`. The existing `Visa Automatic
starten.command` continues to launch the Tkinter application and was not
changed.

## Milestone 4 TRV requirements

The central backend now derives an auditable internal TRV checklist from case
data and confirmed facts. Automatic entries show their rule provenance in the
employee UI and may be reevaluated explicitly. This milestone does not upload,
classify, match, or analyze document files.

## Milestone 5 manual documents

Employees can now upload PDF/JPEG/PNG files to backend-controlled storage,
assign catalog types and people, download them through the API, and manually
match them to structurally compatible requirements. A match is evidence
organization only and does not represent quality approval or automatic
fulfilment. Storage and matching details are documented in
[`backend/DOCUMENTS.md`](backend/DOCUMENTS.md).

## Milestone 6 document classification

Employees may explicitly request a catalog type and existing-person suggestion
for an uploaded file, then accept, correct, or reject it. Suggestions never
silently replace metadata, create matches, fulfil requirements, or assess file
quality. The provider boundary, privacy defaults, and audit lifecycle are
documented in [`backend/CLASSIFICATION.md`](backend/CLASSIFICATION.md).

## Milestone 7 quality and completeness

Employees explicitly run a quality check, inspect structured technical and
type-specific results, and can accept or reject with an auditable reason.
Requirement completeness is evaluated across accepted matched evidence and can
use explicit month coverage without equating file count with coverage. See
[`backend/QUALITY.md`](backend/QUALITY.md). No external AI is enabled by
default, and quality/completeness never advances workflow state directly.

## Milestone 8 WhatsApp fact review

Employees can paste WhatsApp conversation text or upload a bounded `.txt`
export, review deterministic parse diagnostics, and explicitly request
catalog-limited fact suggestions. Suggestions include confidence, evidence, and
source-message traceability and must be accepted, corrected, or rejected before
they can affect confirmed case facts. Conflicts preserve the previous fact and
are surfaced as the backend Next Action. Extraction is disabled by default and
no transcript is sent to an external AI unless a future production provider is
explicitly configured. See [`backend/WHATSAPP.md`](backend/WHATSAPP.md).

## Milestone 9A canonical Canada application

The central backend and employee UI now maintain a typed Canada application
aggregate with explicit applicant selection, purpose review, contextual
addresses, stable ordered histories, official answers, immutable representative
snapshots, and field provenance. This is data maintenance only: it does not call
the existing generator or import legacy/Google data. See
[`backend/CANADA_APPLICATION.md`](backend/CANADA_APPLICATION.md).

## Milestone 9B controlled Canada import

Employees can preview and review existing verified Google CSV,
`.canada-case.json`, and representative-profile sources before applying typed
canonical changes. Conflicts never overwrite confirmed values through the safe
batch, repeated imports reuse stable linked records, and raw source uploads are
not retained. See [`backend/CANADA_IMPORTS.md`](backend/CANADA_IMPORTS.md).
This milestone still does not call a form filler, letter generator, or PDF code.

## Milestone 9C/9D Canada preparation and forms

The backend validates one immutable canonical Canada payload, hashes it, and
passes it through a dedicated adapter to the existing tested IMM5257, IMM5707,
and IMM5476 generator. Generated PDFs are stored privately as auditable
PreparationArtifacts; staleness and integrity drive the PREPARE-to-REVIEW gate.
See [`backend/CANADA_PREPARATION.md`](backend/CANADA_PREPARATION.md) and
[`backend/CANADA_GENERATION.md`](backend/CANADA_GENERATION.md). No Canada letter
generator or external visa submission exists.

## D1 Raspberry Pi staging deployment

The existing application can be packaged for a Raspberry Pi 4 8 GB as a
PostgreSQL/FastAPI/Next.js/Caddy Compose stack with SSD/NVMe bind-mounted
persistence. This is a synthetic-data development/staging target only; the
application still has no production authentication. Follow
[`DEPLOYMENT_D1.md`](DEPLOYMENT_D1.md), including the D1.1 preflight/report
sequence, and do not claim Raspberry validation until every on-device check
actually passes.

## Current workflow

1. Customer completes the existing Google Form.
2. Staff provides either:
   - **Google Forms / Google Sheets CSV export** (preferred), or
   - the current **Google Forms response PDF export** (secondary adapter).
3. The app extracts applicant data.
4. Staff reviews/corrects extracted values and supplies only unresolved 956A-specific values:
   - Title (unless later supplied/inferred from structured sex + marital-status fields)
   - CID, if one exists
   - Date lodged
   - optional RID/TRN
5. Authorised-recipient fields start empty and are entered once in Settings.
6. App generates an editable 956A PDF and leaves signatures blank for Adobe/signing.

## Business rules currently encoded

- Q1: Appointing an authorised recipient
- Q2: Visa applicant
- Q3: CID = Yes only when a CID value is provided; otherwise No
- Q8: `AS ABOVE`
- Q10: blank (one separate 956A per person)
- Q11: No
- Q12: Application process
- Q12 Type of application: `Visitor Visa - Subclass 600`
- Q12 Date lodged: supplied by staff / defaults to today's date in the GUI after reading a source
- Q13 RID/TRN: optional
- Q14-Q19: authorised recipient from local Settings
- Q19: electronic communication = Yes
- Q28/Q29: Appointment selected; signatures remain blank; declaration dates use the generation date

**Important correction:** on this 956A version, the `Application process` branch has a single `Type of application` field. The separate `Subclass of visa` field belongs to the `Cancellation process` branch. Therefore the prototype writes `Visitor Visa - Subclass 600` into `Type of application`.

## Run on macOS (development)

```bash
python3 -m pip install -r requirements.txt
python3 app.py
```

Or double-click `run_mac.command` after allowing it to run.

## Run on Windows (development)

```bat
py -m pip install -r requirements.txt
py app.py
```

## Build a Windows EXE

On a Windows computer, double-click:

`build_windows.bat`

The result is:

`dist\956A_Generator.exe`

Python is not required on the employees' computers after the EXE has been built.

## Recipient settings

Open **Recipient settings...** in the app and enter the Q14-Q19 authorised-recipient data once.
Settings are stored in the user's application-data directory, not inside client PDFs.

## Source reliability

### CSV - preferred
CSV preserves Google Forms answers as structured values. This is the production path.

### Google Forms PDF export - secondary
The old and revised (23-page) print/export is not an AcroForm. The prototype can extract core text answers by question labels across pages without OCR, but selected radio buttons are not structurally encoded. The app therefore does not try to infer them from graphics.

## Data currently extracted from the supplied PDF export

- Family name
- Given names
- Date of birth
- Marital status
- Residential address
- Mobile phone
- Email (kept as source metadata; applicant email is not required in Part A of 956A)

## Safety / validation

The generator refuses to create a final PDF when key applicant or authorised-recipient data is missing. All extracted values remain editable before generation.

## 0.1.1
- Added vertical scrolling to the main application window.
- Added vertical scrolling to Authorised recipient settings.
- Mouse wheel / trackpad scrolling is supported on macOS and Windows.

## Current import and settings behavior

The central backend's Milestone 9C preparation standard is documented in
[`backend/CANADA_PREPARATION.md`](backend/CANADA_PREPARATION.md). It evaluates
canonical data and produces a deterministic semantic payload/hash only; the
legacy desktop generator remains unchanged and is not called by M9C.

- Revised Google Forms exports contain separate City, State and Postcode / CEP questions.
  CSV and PDF imports retain these fields; the UI allows corrections before generation.
- PDF question lookup is independent of page numbers. Example text and printed
  radio/dropdown options are not imported as answers. Blank forms stay blank.
- For printed state/country/marital-status choices, use CSV or enter the answer manually.
- All recipient fields are empty on a fresh installation. Settings from every older
  version preserve saved values and explicit blanks without injecting personal data.
- Q12 is `VISITOR VISA - SUBCLASS 600`; Q28/Q29 use today's local date.
- Automated Windows releases provide an installer and portable ZIP.

### Publish a Windows release from GitHub

Push the repository, then create and push a version tag, for example:

```bash
git tag v0.1.3
git push origin v0.1.3
```

The GitHub workflow `.github/workflows/windows-release.yml` builds the EXE and installer on a real Windows runner and creates a GitHub Release automatically.
