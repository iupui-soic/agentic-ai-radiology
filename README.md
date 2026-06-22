# CritCom

**Critical Results Communication Agent** — an A2A-compatible, FHIR-native AI
agent that automates the radiology critical-results workflow.

CritCom routes signed `DiagnosticReport` resources (or DICOM worklist entries)
to the right ordering physician, tracks acknowledgment as FHIR `Task` resources,
and escalates to the on-call backup if no response arrives within the
ACR-defined timeframe.

## Quick start

```bash
echo 'GOOGLE_API_KEY=AIza...' > .env     # free key: https://aistudio.google.com/apikey
docker compose up -d                     # FHIR + DICOM + auto-seed + agent
```

The agent listens on **`http://localhost:8002`**. Check it's up:

```bash
curl http://localhost:8002/.well-known/agent-card.json
```

Run the full pipeline on a seeded Cat1 case:

```bash
curl -X POST http://localhost:8002/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":"1","method":"message/send",
       "params":{"message":{"role":"user","messageId":"m1",
         "parts":[{"kind":"text","text":"Process DiagnosticReport dr-001"}]}}}'
# → fetches a Type A aortic dissection, dispatches to Dr. Chen,
#   opens an acknowledgment Task with the 60-min Cat1 deadline.
```

More demo scenarios (Cat3 stop-path, DICOM worklist, escalation, audit trail)
live in **[POSTMAN_TESTING.md](POSTMAN_TESTING.md)**.

## How it works

The agent (Google ADK + Gemini) exposes 8 tools and decides which to call:

| Tool | What it does |
|---|---|
| `fetch_report_fhir` | Get a signed DiagnosticReport + ServiceRequest from FHIR |
| `fetch_report_dicom` | C-FIND against a DICOM worklist (fallback when no FHIR) |
| `fetch_radiologist_findings` | Read signed findings from the report broker, then LLM-classify |
| `resolve_provider` | Walk ServiceRequest → ordering / on-call Practitioner |
| `dispatch_communication` | Write a FHIR `Communication` (the notification record) |
| `track_acknowledgment` | Create / check / complete a FHIR `Task` for ack tracking |
| `escalate` | Mark an overdue Task failed, notify on-call, open a new Task |
| `query_audit` | Return the full Communication + Task history for a case |

The LLM only decides *which tool to call next* — every fact in the FHIR record
comes from a deterministic tool reading FHIR/DICOM, never from the model.

> "Notification" today means a FHIR `Communication` is written to HAPI. No
> SMS/page/email transport yet — the audit trail is the deliverable.

## Docs

- **[DOCKER.md](DOCKER.md)** — service diagram, container vs. host addresses, ops.
- **[eval/README.md](eval/README.md)** — the 5-metric performance harness.
- **[POSTMAN_TESTING.md](POSTMAN_TESTING.md)** — full set of demo requests.

## Local development

```bash
docker compose up --build -d         # HAPI :8081, Orthanc :8042/:4242, agent :8002
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt && pip install -e .
```

Key `.env` settings (see `.env.example` for all): `GOOGLE_API_KEY`,
`CRITCOM_LLM_MODEL` (defaults to `gemini-2.5-flash-lite`; avoid
`gemini-2.0-flash`, whose free-tier quota is 0 on most keys), and
`CRITCOM_REQUIRE_API_KEY=false` for open local demos.

## Testing & evaluation

- **Unit tests** — `pytest` runs 45 tests with no network or LLM calls
  (the FHIR client is mocked with `respx`); `pytest -m llm` adds the live-LLM
  classifier tests (needs `GOOGLE_API_KEY`).
- **Performance eval** — a 5-metric harness (ACR accuracy, trajectory F1,
  FHIR state validity, deadline compliance, pass^k) lives in `eval/`. Run it
  with `docker compose --profile eval run --rm critcom-eval`. See
  [eval/README.md](eval/README.md).

## License

MIT