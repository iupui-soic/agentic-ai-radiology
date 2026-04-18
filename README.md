# CritCom — Critical Results Communication Agent

> FHIR-native agent that detects critical findings in radiology reports,
> dispatches ACR-compliant notifications, tracks acknowledgment, and
> escalates when providers don't respond.

Built for the [Prompt Opinion "Agents Assemble" hackathon](https://agents-assemble.devpost.com/).

## Why

Communication failures for critical radiology findings are the **4th most
common allegation** in radiology malpractice claims, with settlements ranging
from $1.75M to $120M. The [Khosravi et al. 2026 roadmap for agentic AI in
radiology](https://doi.org/10.1148/ryai.250651) explicitly identifies a
"Communications Agent" as needed but unbuilt. CritCom closes that gap.

## What it does

1. **Classifies** radiology reports against ACR categories (Cat 1 immediate,
   Cat 2 urgent, Cat 3 routine, or None)
2. **Resolves** the ordering provider via FHIR `ServiceRequest` →
   `Practitioner` / `PractitionerRole` (respecting on-call)
3. **Dispatches** a FHIR `Communication` resource with the finding summary
4. **Tracks** acknowledgment via a linked `Task` resource
5. **Escalates** to a backup when the ack timeout lapses
6. **Exposes** a queryable audit trail

## Architecture

A Google ADK agent (A2A protocol v1, compatible with the
[po-adk-python](https://github.com/prompt-opinion/po-adk-python) starter)
backed by an MCP server exposing 6 tools over a local HAPI FHIR R4 server
seeded with Synthea synthetic data. The LLM is **Claude Sonnet 4.5** via
LiteLLM.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full architecture, state
machine, and tool contracts.

## Quick start

Full setup lives in [`docs/SETUP.md`](docs/SETUP.md). For local development:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env           # add your ANTHROPIC_API_KEY
docker compose up -d fhir      # HAPI FHIR on :8080
pytest -m "not integration and not llm"
```

## What's included (and what isn't)

**Included:** Reading a radiology report, deciding how urgent the finding is,
finding the right doctor to notify, sending the notification through standard
healthcare data formats (FHIR), waiting for them to confirm they got it, and
escalating to a backup if they don't reply in time. Works against a local
test server with fake patient data.

## License

MIT. Synthetic data only — **never real PHI**.
