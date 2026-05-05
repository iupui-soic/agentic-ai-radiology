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
```

Then run any of the demo scenarios below. Each is a single curl that produces
a complete tool trace plus a natural-language summary in the response.

### Demo scenarios

```bash
# A. Cat1 critical finding — full pipeline (fetch → resolve → dispatch → track)
curl -X POST https://pranathi.b691.us/critcom/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send",
       "params":{"message":{"role":"user","messageId":"m1",
         "parts":[{"kind":"text","text":"Process DiagnosticReport dr-001"}]}}}'
# → fetches Type A aortic dissection, dispatches to Dr. Chen,
#   opens Task with 60-min Cat1 deadline.

# B. Cat3 routine finding — agent should STOP (no critical comm needed)
curl -X POST https://pranathi.b691.us/critcom/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"2","method":"message/send",
       "params":{"message":{"role":"user","messageId":"m2",
         "parts":[{"kind":"text","text":"Process DiagnosticReport dr-004"}]}}}'
# → "ACR category Cat3, no critical communication needed."

# C. DICOM fallback path — query the modality worklist
curl -X POST https://pranathi.b691.us/critcom/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"3","method":"message/send",
       "params":{"message":{"role":"user","messageId":"m3",
         "parts":[{"kind":"text","text":"Use the DICOM worklist to fetch the study with accession_number ACC0001."}]}}}'
# → returns full study metadata via DICOM C-FIND against Orthanc.

# D. Escalation — ack timer expired, agent escalates to on-call
curl -X POST https://pranathi.b691.us/critcom/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"4","method":"message/send",
       "params":{"message":{"role":"user","messageId":"m4",
         "parts":[{"kind":"text","text":"Check the acknowledgment status of Task task-overdue-001. If it is overdue and not yet acknowledged, escalate it. The original case was service_request_id sr-002, patient_id patient-002, ACR category Cat2, finding summary: Acute pulmonary emboli involving segmental and subsegmental branches of the right lower lobe pulmonary artery. The escalation timeout should be 1440 minutes."}]}}}'
# → marks the old Task failed, dispatches a new Communication
#   to on-call Dr. Reyes, opens a fresh 24h Task.

# E. Audit trail — full Communication + Task history for a case
curl -X POST https://pranathi.b691.us/critcom/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"5","method":"message/send",
       "params":{"message":{"role":"user","messageId":"m5",
         "parts":[{"kind":"text","text":"Use query_audit_tool to return the full Communication and Task history for service_request_id sr-002."}]}}}'
# → returns every Communication and Task linked to that case.
```

### Seed data available for demos

| ID | Patient | Finding | ACR | Used in |
|---|---|---|---|---|
| `dr-001` | Robert Kowalski | Type A aortic dissection | Cat1 | A |
| `dr-002` | Linh Nguyen | Subsegmental PE | Cat2 | (tied to escalation D/E) |
| `dr-003` | Dorothy Williams | Hypertensive ICH | Cat1 | (Cat1 alt) |
| `dr-004` | Eleanor Goldberg | Stable cholelithiasis | Cat3 | B |
| `ACC0001`–`ACC0003` | (DICOM worklist) | scheduled CT | n/a | C |
| `task-overdue-001` | (overdue ack for sr-002) | — | — | D, E |

---

## Architecture — what runs where

The whole system lives on **one VM** (`pranathi.b691.us`). On that VM there
are three Docker containers and one nginx process:

```
                 Internet  (Prompt Opinion, your curl, browsers)
                     │
                     │  HTTPS  (Let's Encrypt cert)
                     ▼
        ┌────────────────────────────────────────┐
        │  nginx          (host process)         │  ← terminates TLS,
        │   :80, :443                            │    routes by URL path
        └─────────────────┬──────────────────────┘
                          │  http://localhost:8002
                          ▼
        ┌────────────────────────────────────────┐
        │  critcom-agent  (Docker container)     │  ← your AI agent
        │  ADK + LLM, listens on :8001 inside    │    (Gemini-driven,
        │  the container, mapped to host :8002   │     7 tools)
        └────────┬───────────────────┬───────────┘
                 │                   │
                 │  docker network   │  docker network
                 ▼                   ▼
        ┌──────────────────┐  ┌──────────────────┐
        │  critcom-hapi    │  │  critcom-orthanc │
        │  HAPI FHIR       │  │  DICOM server    │
        │  (medical data)  │  │  (imaging meta)  │
        │  :8080 internal  │  │  :8042 + :4242   │
        └──────────────────┘  └──────────────────┘
```

**Plain-English version of the same diagram:**

- The **agent** is the only thing the outside world ever talks to.
- **HAPI** is the agent's private medical-records database. Nobody outside
  the VM can reach it directly; the agent reaches it over the internal
  Docker network.
- **Orthanc** is the agent's private DICOM/imaging database. Same deal —
  internal only.
- **nginx** is the front door: it owns the public domain and the HTTPS cert,
  and it forwards anything matching `https://pranathi.b691.us/critcom/*`
  down to the agent container on `localhost:8002`. nginx exists because:
  Prompt Opinion requires HTTPS, the VM hosts other apps that need to share
  the same domain, and `https://…/critcom/` is friendlier than
  `http://149.165.238.74:8002`.

### Public vs. internal addresses

| Address | Used by |
|---|---|
| `https://pranathi.b691.us/critcom/` | Prompt Opinion, your curl, browsers — the **only** public entry |
| `http://localhost:8002` (on the VM) | nginx, when forwarding requests to the agent |
| `http://hapi-fhir:8080/fhir` | The agent itself, from inside the Docker network |
| `http://orthanc:8042` | The agent itself, from inside the Docker network |
| `http://localhost:8081/fhir` (on the VM) | You, when SSH'd into the VM and poking around HAPI manually |

Containers refer to each other by **service name** (`hapi-fhir`, `orthanc`,
`critcom-agent`) — that's why the agent's `.env` says
`CRITCOM_FHIR_BASE_URL=http://hapi-fhir:8080/fhir` and not `localhost`.

### Local dev is the same shape, minus nginx

When you run `docker compose up` on your laptop, you get the three
containers but no nginx and no HTTPS. You hit the agent directly at
`http://localhost:8002`. Same code, same wiring, just no public layer.

---

## What happens when you call the agent

A worked example: you POST `"Process DiagnosticReport dr-001"` to the agent.

```
You / Prompt Opinion
        │  POST https://pranathi.b691.us/critcom/
        │  body: A2A JSON-RPC "message/send"
        ▼
nginx → critcom-agent
        │
        │  ADK runtime hands the message to the LLM (Gemini 2.5 Flash Lite)
        │  along with the system prompt and the 7 available tools.
        ▼
LLM decides: "I need to fetch the report first."
        │
        ▼
TOOL 1: fetch_report_fhir_tool({"diagnostic_report_id": "dr-001"})
        │
        │  → Agent calls HAPI: GET http://hapi-fhir:8080/fhir/DiagnosticReport/dr-001
        │  → HAPI returns the resource
        │  → Tool normalizes it into a CritComStudy:
        │       { acr_category: "Cat1",
        │         service_request_id: "sr-001",
        │         patient_id: "patient-001",
        │         report_text: "TYPE A AORTIC DISSECTION ..." }
        │
        ▼
LLM sees acr_category = "Cat1" → critical, must continue.
        │
        ▼
TOOL 2: resolve_provider_tool({"service_request_id": "sr-001"})
        │
        │  → Agent calls HAPI: GET ServiceRequest/sr-001
        │  → Reads .requester → Practitioner/practitioner-001
        │  → Fetches that Practitioner + their PractitionerRole
        │  → Returns: Dr. Michael Wei Chen, phone, pager, email
        │
        ▼
TOOL 3: dispatch_communication_tool({...})
        │
        │  → Agent BUILDS a FHIR Communication resource:
        │       status="in-progress", category="Cat1",
        │       subject=Patient/patient-001,
        │       about=ServiceRequest/sr-001,
        │       recipient=Practitioner/practitioner-001,
        │       sent=<now>, payload=<finding text>
        │  → Agent POSTs it to HAPI: POST /Communication
        │  → HAPI assigns ID 1017 and persists to disk
        │  → Tool returns: {communication_id: "1017", sent: "..."}
        │
        ▼
TOOL 4: track_acknowledgment_tool({"action": "create",
                                    "communication_id": "1017",
                                    "timeout_minutes": 60, ...})
        │
        │  → Agent BUILDS a FHIR Task:
        │       status="requested",
        │       focus=Communication/1017,
        │       owner=Practitioner/practitioner-001,
        │       restriction.period.end=<now + 60 minutes>
        │  → Agent POSTs it to HAPI: POST /Task
        │  → HAPI assigns ID 1018 and persists
        │  → Tool returns: {task_id: "1018", deadline: "..."}
        │
        ▼
LLM sees all four tools succeeded.
        │
        ▼
Agent responds with a natural-language summary of what it did,
plus the full machine-readable history of every tool call and return.
```

### What you'd see in HAPI afterwards

Two new resources, persistent on the VM disk:

```bash
# The notification record
curl http://localhost:8081/fhir/Communication/1017
#  → category Cat1, recipient practitioner-001, payload = the finding text

# The acknowledgment-tracking task with the 60-minute Cat1 deadline
curl http://localhost:8081/fhir/Task/1018
#  → status requested, owner practitioner-001,
#     restriction.period.end = sent + 60 min
```

If 60 minutes pass without acknowledgment, the next call to the agent
(`"Check Task 1018"`) would invoke `track_acknowledgment_tool` with
`action="check"`, see the deadline has passed, and call `escalate_tool` —
which marks Task 1018 failed, resolves the on-call provider
(`practitioner-oncall-001`), and creates a fresh Communication + Task
for them.

### Where the LLM fits

The LLM **does not** invent medical facts, IDs, or contact info. It only
decides *which tool to call next* based on the data the previous tool
returned. Every fact in the final FHIR record came from a deterministic
tool reading FHIR/DICOM. The LLM is the dispatcher; the tools are the truth.

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

## Roadmap / possible enhancements

Things that would make the system feel more production-grade. None are required
for the current submission scope.

- **Real DICOM images from TCIA.** Pull a handful of anonymized chest CTs from
  [The Cancer Imaging Archive](https://www.cancerimagingarchive.net/) and push
  them into Orthanc as completed studies, with the synthetic `.wl` worklist
  entries updated to reference those real study UIDs. Adds visual flair for
  demos. Note: Modality Worklist data itself is per-hospital operational state
  and isn't publicly distributed, so the synthetic worklist generation has to
  stay regardless.
- **Synthea-generated patients.** Use [Synthea](https://github.com/synthetichealth/synthea)
  to seed 50–100 synthetic patients with full longitudinal FHIR histories
  (demographics, prior conditions, meds). Lets the agent operate against a
  realistic-sized chart, not just 4 curated patients.
- **Modality variety.** Today all seed cases are CT. Add an MRI brain (acute
  stroke alert) and an ultrasound (ruptured AAA) to demonstrate the agent
  isn't modality-specific.
- **Real notification channels.** `dispatch_communication` writes a FHIR
  `Communication` today but doesn't actually send anything. Wire in Twilio
  (SMS), a hospital paging API, or Direct secure email so notifications
  reach the recipient out-of-band. The audit trail already exists; this is
  purely a transport layer.
- **Outcome metrics dashboard.** Time-to-acknowledgment, escalation rate by
  category, by service line, etc. — all derivable from the existing FHIR
  Communication + Task records via standard FHIR search.
- **Acknowledgment via inbound A2A.** Today the only way to mark a Task
  completed is calling `track_acknowledgment(action=mark_acknowledged)`
  through the agent. A small inbound webhook (or a "respond" message from
  the recipient's own agent) would close the loop end-to-end.

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