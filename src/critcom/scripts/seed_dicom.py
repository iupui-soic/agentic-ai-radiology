"""
critcom-seed-dicom — generate DICOM Modality Worklist (.wl) files matching the
synthetic patients in seed_bundle.json and upload them to Orthanc via REST API.

Usage:
    python -m critcom.scripts.seed_dicom
    # or:
    critcom-seed-dicom

Required env vars:
    CRITCOM_ORTHANC_URL       e.g. http://localhost:8042
    CRITCOM_ORTHANC_USER      default: orthanc
    CRITCOM_ORTHANC_PASSWORD  default: orthanc
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
from datetime import datetime

import httpx
import structlog

log = structlog.get_logger(__name__)


# Three studies, one per patient — priorities chosen to match the FHIR seed
WORKLIST_ENTRIES = [
    {
        "patient_id": "patient-001",
        "patient_name": "Kowalski^Robert^James",
        "patient_birth_date": "19660314",
        "patient_sex": "M",
        "accession_number": "ACC0001",
        "study_uid": "1.2.826.0.1.3680043.8.498.10000000001",
        "modality": "CT",
        "priority": "STAT",
        "description": "CT Chest/Abdomen/Pelvis with contrast",
    },
    {
        "patient_id": "patient-002",
        "patient_name": "Nguyen^Linh^Thu",
        "patient_birth_date": "19760722",
        "patient_sex": "F",
        "accession_number": "ACC0002",
        "study_uid": "1.2.826.0.1.3680043.8.498.10000000002",
        "modality": "CT",
        "priority": "HIGH",
        "description": "CT Pulmonary Angiography",
    },
    {
        "patient_id": "patient-003",
        "patient_name": "Williams^Dorothy^Mae",
        "patient_birth_date": "19511108",
        "patient_sex": "F",
        "accession_number": "ACC0003",
        "study_uid": "1.2.826.0.1.3680043.8.498.10000000003",
        "modality": "CT",
        "priority": "STAT",
        "description": "CT Head without contrast",
    },
]


def _build_worklist_dataset(entry: dict) -> "Dataset":  # type: ignore[name-defined]
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.31"  # MWL
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    file_meta.ImplementationClassUID = generate_uid()

    ds = Dataset()
    ds.file_meta = file_meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False

    today = datetime.now()
    ds.PatientName = entry["patient_name"]
    ds.PatientID = entry["patient_id"]
    ds.PatientBirthDate = entry["patient_birth_date"]
    ds.PatientSex = entry["patient_sex"]
    ds.AccessionNumber = entry["accession_number"]
    ds.StudyInstanceUID = entry["study_uid"]
    ds.RequestedProcedureID = entry["accession_number"]
    ds.RequestedProcedureDescription = entry["description"]
    ds.RequestedProcedurePriority = entry["priority"]
    ds.Modality = entry["modality"]

    sps = Dataset()
    sps.ScheduledStationAETitle = "MODALITY1"
    sps.ScheduledProcedureStepStartDate = today.strftime("%Y%m%d")
    sps.ScheduledProcedureStepStartTime = today.strftime("%H%M%S")
    sps.Modality = entry["modality"]
    sps.ScheduledPerformingPhysicianName = ""
    sps.ScheduledProcedureStepDescription = entry["description"]
    sps.ScheduledProcedureStepID = entry["accession_number"]
    sps.ScheduledProcedureStepStatus = "SCHEDULED"
    ds.ScheduledProcedureStepSequence = [sps]
    return ds


def _upload_worklist(orthanc_url: str, auth: tuple[str, str], dataset) -> None:
    """Upload via Orthanc REST API."""
    with tempfile.NamedTemporaryFile(suffix=".wl", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        from pydicom import dcmwrite
        dcmwrite(tmp_path, dataset, write_like_original=False)
        with open(tmp_path, "rb") as fh:
            data = fh.read()
        # Orthanc's worklist plugin watches a directory; the REST API supports
        # uploading to /tools/create-worklist if available, otherwise we fall
        # back to writing the file into the worklists volume.
        url = f"{orthanc_url.rstrip('/')}/instances"
        try:
            r = httpx.post(url, content=data, auth=auth, timeout=10.0)
            if r.status_code >= 400:
                log.warning("seed_dicom.instances_endpoint_failed", status=r.status_code, body=r.text[:200])
        except Exception as e:
            log.warning("seed_dicom.upload_failed", error=str(e))
    finally:
        pathlib.Path(tmp_path).unlink(missing_ok=True)


def _write_to_worklist_directory(out_dir: pathlib.Path, entry: dict, dataset) -> pathlib.Path:
    """Write the .wl file into a host directory mounted into Orthanc's worklist volume."""
    from pydicom import dcmwrite
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{entry['accession_number']}.wl"
    dcmwrite(str(out_path), dataset, write_like_original=False)
    return out_path


def main() -> None:
    try:
        import pydicom  # noqa: F401
    except ImportError:
        print("ERROR: pydicom not installed. Run: pip install pydicom pynetdicom", file=sys.stderr)
        sys.exit(1)

    out_dir = pathlib.Path(os.getenv("CRITCOM_DICOM_WORKLIST_DIR", "./orthanc-worklists"))
    orthanc_url = os.getenv("CRITCOM_ORTHANC_URL", "http://localhost:8042")
    auth = (
        os.getenv("CRITCOM_ORTHANC_USER", "orthanc"),
        os.getenv("CRITCOM_ORTHANC_PASSWORD", "orthanc"),
    )

    written: list[pathlib.Path] = []
    for entry in WORKLIST_ENTRIES:
        ds = _build_worklist_dataset(entry)
        path = _write_to_worklist_directory(out_dir, entry, ds)
        written.append(path)
        log.info("seed_dicom.wrote", file=str(path), accession=entry["accession_number"], priority=entry["priority"])
        # Best-effort REST upload (Orthanc may not accept worklist files via /instances;
        # the directory write above is the primary mechanism).
        _upload_worklist(orthanc_url, auth, ds)

    print(f"✓ Wrote {len(written)} worklist files to {out_dir}/")
    print(f"  Mount this directory into Orthanc as /var/lib/orthanc/worklists for them to be served.")
    for p in written:
        print(f"  - {p.name}")


if __name__ == "__main__":
    main()
