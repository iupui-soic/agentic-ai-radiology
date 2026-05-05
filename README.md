# CritCom

> **Critical Results Communication Agent** — an A2A-compatible, FHIR-native AI
> agent that automates the radiology critical-results workflow.

Built for the [Prompt Opinion](https://promptopinion.ai) Agents Assemble
competition. CritCom routes signed `DiagnosticReport` resources (or DICOM
worklist entries) to the right ordering physician, tracks acknowledgment as
FHIR `Task` resources, and escalates to the on-call backup if no response is
received within the ACR-defined timeframe.

---

## What's in this repo

```
critcom/
├── critcom_agent/           # ADK Agent — instruction, tool wiring, A2A app
│   ├── agent.py
│   └── app.py
├── shared/                  # po-adk-python style infrastructure
│   ├── middleware.py        # X-API-Key auth + A2A metadata bridging
│   ├── fhir_hook.py         # before_model_callback that extracts FHIR ctx
│   ├── app_factory.py       # create_a2a_app()
│   ├── logging_utils.py
│   └── tools/               # ADK-compatible wrappers around critcom.tools
├── src/critcom/
│   ├── fhir/                # Pydantic FHIR R4 models + async client
│   ├── classification/      # ACR classifier (used in tests / future LLM path)
│   ├── tools/               # 7 MCP tools (the actual logic)
│   └── scripts/             # seed.py (HAPI), seed_dicom.py (Orthanc)
├── tests/
│   ├── fixtures/
│   │   ├── fhir/seed_bundle.json     # synthetic FHIR data
│   │   └── reports/sample_reports.json
│   └── test_*.py
├── docker-compose.yml       # HAPI FHIR + Orthanc + agent
├── Dockerfile
├── pyproject.toml
└── .env.example
```

---

## Quick start

### 1. Clone and configure

```bash
git clone https://github.com/iupui-soic/agentic-ai-radiology.git
cd agentic-ai-radiology
cp .env.example .env
# Edit .env — set GOOGLE_API_KEY and CRITCOM_API_KEY
```

### 2. Start the stack with Docker Compose

```bash
docker compose up --build
```

This starts:
- **HAPI FHIR** on `http://localhost:8080/fhir`
- **Orthanc** on `http://localhost:8042` (UI) and `localhost:4242` (DICOM)
- **CritCom agent** on `http://localhost:8001`

### 3. Seed synthetic data (in another terminal)

```bash
# Install in dev mode
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .

# Load FHIR seed
critcom-seed

# Generate DICOM worklist files
critcom-seed-dicom
```

### 4. Verify

```bash
# Agent card
curl http://localhost:8001/.well-known/agent-card.json

# FHIR resources
curl 'http://localhost:8080/fhir/Patient/patient-001'
curl 'http://localhost:8080/fhir/DiagnosticReport/dr-001'

# DICOM Orthanc UI
open http://localhost:8042   # login: orthanc / orthanc
```

### 5. Run tests

```bash
pytest -v
```

---

## Configuration

All settings live in `.env`. The most important ones:

| Variable | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini model (free tier from AI Studio) |
| `CRITCOM_API_KEY` | API key Prompt Opinion sends in `X-API-Key` |
| `CRITCOM_FHIR_BASE_URL` | HAPI FHIR base URL |
| `CRITCOM_DICOM_HOST` / `_PORT` / `_AET` | Orthanc DICOM endpoint |
| `CRITCOM_FHIR_EXTENSION_URI` | A2A metadata extension URI for FHIR context — match your Prompt Opinion workspace |
| `CRITCOM_CAT1_ACK_TIMEOUT_MINUTES` | ACR Cat1 ack deadline (default 60) |
| `CRITCOM_CAT2_ACK_TIMEOUT_MINUTES` | ACR Cat2 ack deadline (default 1440) |

---

## The 7 MCP tools

| Tool | What it does |
|---|---|
| `fetch_report_fhir` | Get a signed DiagnosticReport + linked ServiceRequest from FHIR |
| `fetch_report_dicom` | C-FIND query against a DICOM MWL (fallback when no FHIR) |
| `resolve_provider` | Walk ServiceRequest → Practitioner / on-call PractitionerRole |
| `dispatch_communication` | Create a FHIR `Communication` resource — notification record |
| `track_acknowledgment` | Create / check / complete a FHIR `Task` for ack tracking |
| `escalate` | Mark overdue Task failed, notify on-call, create new Task |
| `query_audit` | Return full Communication + Task history for a case |

---

## Workflow

```
1. Trigger
   ├── FHIR: new DiagnosticReport status="final"
   └── DICOM: completed worklist entry

2. fetch_report_{fhir,dicom}
   └── Returns CritComStudy { priority, acr_category, IDs, text }

3. Read ACR category from DiagnosticReport
   └── Cat3 / None  →  log only, stop
       Cat1 / Cat2  →  continue

4. resolve_provider
   └── ServiceRequest.requester → Practitioner contact

5. dispatch_communication  →  FHIR Communication
6. track_acknowledgment    →  FHIR Task with deadline
7. If timeout: escalate    →  on-call provider, new Task

All audit data — Communications + Tasks — is written to FHIR regardless of
whether the trigger came from FHIR or DICOM.
```

`ServiceRequest.priority` (FHIR) and `Requested Procedure Priority` (DICOM)
control the **agent processing queue order** only. The clinical urgency (ACR
category) comes from the report itself.

---

## Deployment to Google Cloud Run

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT

# Store secrets
echo -n "your-google-api-key" | gcloud secrets create google-api-key --data-file=-
echo -n "your-critcom-api-key" | gcloud secrets create critcom-api-key --data-file=-

# Deploy
gcloud run deploy critcom-agent \
  --source . \
  --region us-central1 \
  --set-env-vars "AGENT_MODULE=critcom_agent.app:a2a_app,GOOGLE_GENAI_USE_VERTEXAI=FALSE,CRITCOM_FHIR_BASE_URL=https://your-vm.example.com:8080/fhir" \
  --set-secrets "GOOGLE_API_KEY=google-api-key:latest,CRITCOM_API_KEY=critcom-api-key:latest" \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 3
```

Then point your HAPI FHIR base URL at your VM, and register the agent card URL
on the Prompt Opinion platform.

---

## License

MIT
