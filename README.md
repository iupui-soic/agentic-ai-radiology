# CritCom

> **Critical Results Communication Agent** — an A2A-compatible, FHIR-native AI
> agent that automates the radiology critical-results workflow.

Built for the [Prompt Opinion](https://promptopinion.ai) Agents Assemble
competition. CritCom routes signed `DiagnosticReport` resources (or DICOM
worklist entries) to the right ordering physician, tracks acknowledgment as
FHIR `Task` resources, and escalates to the on-call backup if no response is
received within the ACR-defined timeframe.

---

## Try it without installing anything

The agent is live at **`https://pranathi.b691.us/critcom`**.

```bash
# 1. Read the public agent card (A2A discovery)
curl https://pranathi.b691.us/critcom/.well-known/agent-card.json

# 2. Send the agent a real task (full tool chain runs against live HAPI FHIR)
curl -X POST https://pranathi.b691.us/critcom/ \
  -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0","id":"1","method":"message/send",
    "params":{"message":{"role":"user","messageId":"m1",
      "parts":[{"kind":"text","text":"Process DiagnosticReport dr-001"}]}}
  }'
```

The response shows every tool the agent invoked, with arguments and return
values, plus the final natural-language summary. Seed reports `dr-001` (Cat1
aortic dissection), `dr-002` (Cat1 PE), and `dr-003` (Cat1 ICH) are all valid
inputs.

---

## Local development

### 1. Clone and configure

```bash
git clone https://github.com/iupui-soic/agentic-ai-radiology.git
cd agentic-ai-radiology
git checkout dev_parvati          # active branch — see "Branches" below
cp .env.example .env
```

Edit `.env`:
- Set `GOOGLE_API_KEY` (free key from https://aistudio.google.com/apikey).
- Set `CRITCOM_LLM_MODEL=gemini-2.5-flash-lite` — the default `gemini-2.0-flash`
  is in a free-tier quota bucket that gets exhausted fast.
- Leave `CRITCOM_REQUIRE_API_KEY=false` for local dev.

### 2. Start the stack

```bash
docker compose up --build -d
```

This starts:
| Service | Host port | Container port |
|---|---|---|
| HAPI FHIR | `:8081` | `:8080` |
| Orthanc REST/UI | `:8042` | `:8042` |
| Orthanc DICOM | `:4242` | `:4242` |
| CritCom agent | `:8002` | `:8001` |

> Host ports `8081`/`8002` are deliberately offset from defaults to avoid
> collisions on the deploy VM. Inside the docker network the agent still talks
> to HAPI on `:8080` — only host-side ports are remapped.

### 3. Install the Python package and seed data

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e .

critcom-seed         # 17 FHIR resources into HAPI
critcom-seed-dicom   # synthetic worklist entries into Orthanc
```

### 4. Verify

```bash
# Agent card (note port 8002, not 8001)
curl http://localhost:8002/.well-known/agent-card.json

# FHIR
curl http://localhost:8081/fhir/Patient/patient-001
curl http://localhost:8081/fhir/DiagnosticReport/dr-001

# Run the agent end-to-end
curl -X POST http://localhost:8002/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send",
       "params":{"message":{"role":"user","messageId":"m1",
         "parts":[{"kind":"text","text":"Process DiagnosticReport dr-001"}]}}}'

# Orthanc UI (login: orthanc / orthanc)
open http://localhost:8042
```

### 5. Run the test suite

```bash
pytest -v             # 35 tests, no LLM calls
pytest -v -m llm      # +2 tests that hit the real LLM (needs GOOGLE_API_KEY)
```

---

## Project layout

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
│   ├── tools/               # 7 tools — the actual logic
│   └── scripts/             # seed.py (HAPI), seed_dicom.py (Orthanc)
├── tests/
│   ├── fixtures/
│   │   ├── fhir/seed_bundle.json
│   │   └── reports/sample_reports.json
│   └── test_*.py
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

---

## The 7 tools

| Tool | What it does |
|---|---|
| `fetch_report_fhir` | Get a signed DiagnosticReport + linked ServiceRequest from FHIR |
| `fetch_report_dicom` | C-FIND query against a DICOM MWL (fallback when no FHIR) |
| `resolve_provider` | Walk ServiceRequest → Practitioner / on-call PractitionerRole |
| `dispatch_communication` | Create a FHIR `Communication` resource — notification record |
| `track_acknowledgment` | Create / check / complete a FHIR `Task` for ack tracking |
| `escalate` | Mark overdue Task failed, notify on-call, create new Task |
| `query_audit` | Return full Communication + Task history for a case |

> "Notification" today means a FHIR `Communication` resource is written to HAPI.
> No SMS/page/email integration yet — the audit trail is the deliverable.

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
```

`ServiceRequest.priority` (FHIR) and `Requested Procedure Priority` (DICOM)
control the **agent processing queue order** only. The clinical urgency (ACR
category) comes from the report itself.

---

## Configuration

All settings live in `.env`. The most important ones:

| Variable | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini model (free tier from AI Studio) |
| `CRITCOM_LLM_MODEL` | Use `gemini-2.5-flash-lite` (others are quota-exhausted) |
| `CRITCOM_API_KEY` | API key Prompt Opinion sends in `X-API-Key` |
| `CRITCOM_REQUIRE_API_KEY` | Set `false` for local dev / open demo |
| `CRITCOM_FHIR_BASE_URL` | HAPI FHIR base URL |
| `CRITCOM_DICOM_HOST` / `_PORT` / `_AET` | Orthanc DICOM endpoint |
| `CRITCOM_FHIR_EXTENSION_URI` | A2A metadata extension URI for FHIR context |
| `CRITCOM_CAT1_ACK_TIMEOUT_MINUTES` | ACR Cat1 ack deadline (default 60) |
| `CRITCOM_CAT2_ACK_TIMEOUT_MINUTES` | ACR Cat2 ack deadline (default 1440) |

---

## Deployment

CritCom is deployed to a single VM (`pranathi.b691.us`) running Docker
Compose behind nginx with Let's Encrypt TLS. The same `docker-compose.yml`
that runs locally runs in production.

**On the VM:**

```bash
ssh plhi@pranathi.b691.us
cd ~/critcom
git pull origin dev_parvati
docker-compose build critcom-agent          # NOTE: hyphenated, v1 is installed
docker rm -f critcom-agent                  # see "Troubleshooting" below
docker-compose up -d critcom-agent
```

nginx terminates TLS at `/critcom/` and proxies to `localhost:8002`. The
location block lives in `/etc/nginx/sites-enabled/default` and forwards
`Host`, `X-Forwarded-Proto`, and `X-Forwarded-Prefix /critcom`.

The `dev` branch is kept in sync; PRs from `dev_parvati` → `dev` → `main`.

---

## Troubleshooting

**`KeyError: 'ContainerConfig'` on `docker-compose up`**
Bug in docker-compose v1.29.2 against newer Docker daemons (BuildKit images).
Workaround: `docker rm -f critcom-agent` then `docker-compose up -d
critcom-agent`. Affects the VM only — Docker Desktop on Mac uses compose v2.

**`429 RESOURCE_EXHAUSTED` from Gemini**
The free-tier daily request quota for `gemini-2.0-flash` and
`gemini-2.0-flash-lite` is `0` on most personal API keys. Set
`CRITCOM_LLM_MODEL=gemini-2.5-flash-lite` and restart the agent container.

**`503 UNAVAILABLE` from `gemini-2.5-flash`**
Transient — the model is overloaded. Retry, or fall back to
`gemini-2.5-flash-lite`.

**`Object of type datetime is not JSON serializable`**
Fixed in commit `ca294b3` (FHIR client `model_dump` calls switched to
`mode="json"`). Pull and rebuild if you see it.

**Agent card returns `skills: []`**
You're on a stale image. Rebuild: `docker-compose build critcom-agent` then
the rm-then-up workaround above. Container code is COPYed at build time, not
bind-mounted — `restart` alone won't pick up code changes.

---

## Branches

- `main` — submission baseline
- `dev` — integration branch
- `dev_parvati` — **active branch**, all current work lands here

If you `git pull` and see a force-push warning, run
`git fetch && git reset --hard origin/dev_parvati`. There was one rewrite of
history early on to strip auto-generated commit trailers.

---

## License

MIT