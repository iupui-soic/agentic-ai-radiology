"""
critcom-seed — load synthetic FHIR test data into a local HAPI FHIR server.

Usage:
    python -m critcom.scripts.seed
    # or via entry point:
    critcom-seed
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys

import structlog

from critcom.fhir.client import FHIRClient

log = structlog.get_logger(__name__)

FIXTURES_DIR = pathlib.Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / "fhir"


async def seed() -> None:
    bundle_path = FIXTURES_DIR / "seed_bundle.json"
    if not bundle_path.exists():
        log.error("seed.bundle_not_found", path=str(bundle_path))
        sys.exit(1)

    bundle = json.loads(bundle_path.read_text())
    log.info("seed.loading", entries=len(bundle.get("entry", [])))

    async with FHIRClient.from_env() as client:
        result = await client.transaction_bundle(bundle)

    total = len(result.get("entry", []))
    log.info("seed.done", resources_written=total)
    print(f"✓ Seeded {total} resources into {client._base_url}")


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
