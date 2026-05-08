"""
critcom-seed-dicom-dcm4che — generate dcm4che-style DICOM Modality Worklist
(.wl) sample files representing scenarios from sites without FHIR.

These samples deliberately use DIFFERENT patient identifiers than the FHIR
seed bundle (which represents a modern FHIR-enabled site). The DICOM samples
represent independent legacy-site deployments, demonstrating that CritCom
handles both contexts.

Usage:
    python -m critcom.scripts.seed_dicom_dcm4che
    # or:
    critcom-seed-dicom-dcm4che

Override output dir with CRITCOM_DICOM_WORKLIST_DIR (defaults to ./orthanc-worklists).

Citation:
    dcm4che project — open-source DICOM toolkit (HL7-affiliated).
    https://github.com/dcm4che/dcm4che
    These samples are authored using pydicom to match the structure of
    dcm4che's reference test fixtures for Modality Worklist.
"""

from __future__ import annotations

import os
import pathlib
import sys

import structlog

log = structlog.get_logger(__name__)


# Three samples mirroring the variety in dcm4che's test fixtures:
# different modalities, different priorities, different demographics.
DCM4CHE_LIKE_SAMPLES = [
    {
        "name": "wlitem-001.wl",
        "patient_name": "Mueller^Hans^Dieter",
        "patient_id": "DCM4CHE-PT001",
        "accession": "ACC-DCM-001",
        "modality": "CT",
        "priority": "STAT",
        "description": "CT Head without contrast",
    },
    {
        "name": "wlitem-002.wl",
        "patient_name": "Schmidt^Greta^Annelise",
        "patient_id": "DCM4CHE-PT002",
        "accession": "ACC-DCM-002",
        "modality": "MR",
        "priority": "ROUTINE",
        "description": "MR Lumbar Spine without contrast",
    },
    {
        "name": "wlitem-003.wl",
        "patient_name": "Lopez^Maria^Carmen",
        "patient_id": "DCM4CHE-PT003",
        "accession": "ACC-DCM-003",
        "modality": "DX",
        "priority": "HIGH",
        "description": "Chest X-Ray PA and Lateral",
    },
]


def _make_worklist_dataset(
    patient_name: str,
    patient_id: str,
    accession: str,
    modality: str,
    priority: str,
    description: str,
) -> "Dataset":  # type: ignore[name-defined]
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
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.AccessionNumber = accession
    ds.StudyInstanceUID = generate_uid()
    ds.RequestedProcedureID = accession
    ds.RequestedProcedureDescription = description
    ds.RequestedProcedurePriority = priority
    ds.Modality = modality

    sps = Dataset()
    sps.ScheduledStationAETitle = "MODALITY1"
    sps.ScheduledProcedureStepStartDate = "20260505"
    sps.ScheduledProcedureStepStartTime = "090000"
    sps.Modality = modality
    sps.ScheduledProcedureStepDescription = description
    sps.ScheduledProcedureStepID = accession
    sps.ScheduledProcedureStepStatus = "SCHEDULED"
    ds.ScheduledProcedureStepSequence = [sps]
    return ds


def main() -> None:
    try:
        import pydicom  # noqa: F401
    except ImportError:
        print("ERROR: pydicom not installed. Run: pip install pydicom pynetdicom", file=sys.stderr)
        sys.exit(1)

    from pydicom import dcmwrite

    out_dir = pathlib.Path(os.getenv("CRITCOM_DICOM_WORKLIST_DIR", "./orthanc-worklists"))
    out_dir.mkdir(parents=True, exist_ok=True)

    written: list[pathlib.Path] = []
    for sample in DCM4CHE_LIKE_SAMPLES:
        sample_args = dict(sample)
        out_name = sample_args.pop("name")
        ds = _make_worklist_dataset(**sample_args)
        out_path = out_dir / out_name
        dcmwrite(str(out_path), ds, write_like_original=False)
        written.append(out_path)
        log.info(
            "seed_dicom_dcm4che.wrote",
            file=str(out_path),
            accession=sample_args["accession"],
            priority=sample_args["priority"],
            modality=sample_args["modality"],
        )

    print(f"✓ Wrote {len(written)} dcm4che-style worklist files to {out_dir}/")
    for p in written:
        print(f"  - {p.name}")
    print(
        "\nThese are picked up automatically by Orthanc when its worklists volume"
        f"\nis mounted at {out_dir.resolve()}."
    )


if __name__ == "__main__":
    main()