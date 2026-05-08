"""
critcom-seed-dicom-dcmtk — pull real DICOM Modality Worklist test fixtures
from the OFFIS DCMTK reference toolkit and write them into the repo's
orthanc-worklists/ directory.

This is the citable production fixture source for the paper. DCMTK is the
peer-reviewed reference DICOM toolkit:

    Eichelberg M, Riesmeier J, Wilkens T, Hewett AJ, Barth A, Jensch P.
    Ten years of medical imaging standardization and prototypical
    implementation: the DICOM standard and the OFFIS DICOM toolkit (DCMTK).
    Proc SPIE Medical Imaging. 2004;5371:57-68.

Usage:
    critcom-seed-dicom-dcmtk
    # or:
    python -m critcom.scripts.seed_dicom_dcmtk

Env vars:
    CRITCOM_DICOM_WORKLIST_DIR   (default: ./orthanc-worklists)
    CRITCOM_DCMTK_CACHE_DIR      (default: ./.dcmtk-cache)
    CRITCOM_DCMTK_REF            (default: master)  — git ref to clone

The script is idempotent — it caches the DCMTK clone under the cache dir
and re-converts fixtures into .wl files on each run. Safe to re-run after
git pulls; safe to run on a fresh checkout.
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from pydicom.dataset import Dataset

log = structlog.get_logger(__name__)

DCMTK_REPO = "https://github.com/DCMTK/dcmtk.git"

# DCMTK ships its MWL fixtures here. Path is stable as of master at time of
# writing; if it moves the script falls through to a search.
WLISTDB_RELPATH = pathlib.Path("dcmwlm") / "data" / "wlistdb" / "OFFIS"

# DCMTK dump line format:  (gggg,eeee) VR  VALUE
# VALUE is plain text, optionally wrapped in [...] for some types.
_LINE_RE = re.compile(
    r"\s*\(([0-9a-fA-F]{4}),([0-9a-fA-F]{4})\)\s+(\w{2})\s*(.*?)\s*$"
)


def _clean_value(raw: str) -> str:
    if raw.startswith("[") and raw.endswith("]"):
        return raw[1:-1]
    return raw


def _parse_dump(text: str) -> "Dataset":
    """Parse a DCMTK .dump file into a pydicom Dataset.

    Handles top-level elements + one nested level of sequence (which is
    everything MWL fixtures need). Skips elements pydicom can't validate
    rather than failing the whole file.
    """
    from pydicom.dataset import Dataset
    from pydicom.datadict import keyword_for_tag

    ds = Dataset()
    current_seq: str | None = None
    current_item: Dataset | None = None

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if "(fffe,e000)" in line.lower():  # start of sequence item
            current_item = Dataset()
            continue
        if "(fffe,e00d)" in line.lower():  # end of sequence item
            if current_item is not None and current_seq is not None:
                seq = list(getattr(ds, current_seq, []))
                seq.append(current_item)
                setattr(ds, current_seq, seq)
                current_item = None
            continue
        if "(fffe,e0dd)" in line.lower():  # end of sequence
            current_seq = None
            current_item = None
            continue

        m = _LINE_RE.match(line)
        if not m:
            continue
        group, element, vr, value = m.groups()
        tag = (int(group, 16), int(element, 16))
        value = _clean_value(value or "")

        if vr.upper() == "SQ":
            try:
                kw = keyword_for_tag(tag)
            except Exception:
                kw = None
            if kw:
                current_seq = kw
                setattr(ds, kw, [])
            continue

        try:
            target = current_item if current_item is not None else ds
            target.add_new(tag, vr, value if value else None)
        except Exception:
            # Skip elements we can't parse — better to keep the rest than fail.
            pass

    return ds


def _ensure_dcmtk_clone(cache_dir: pathlib.Path, ref: str) -> pathlib.Path:
    """Sparse-clone (or update) DCMTK's dcmwlm/data subdirectory into cache."""
    repo_dir = cache_dir / "dcmtk"
    if not repo_dir.exists():
        log.info("seed_dicom_dcmtk.cloning", target=str(repo_dir))
        repo_dir.mkdir(parents=True)
        subprocess.run(["git", "init", "-q"], cwd=repo_dir, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", DCMTK_REPO],
            cwd=repo_dir, check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "config", "core.sparseCheckout", "true"],
            cwd=repo_dir, check=True, capture_output=True,
        )
        sparse = repo_dir / ".git" / "info" / "sparse-checkout"
        sparse.write_text("dcmwlm/data/\n")
        subprocess.run(
            ["git", "pull", "--depth=1", "origin", ref],
            cwd=repo_dir, check=True, capture_output=True,
        )
    else:
        log.info("seed_dicom_dcmtk.cache_hit", repo=str(repo_dir))
    return repo_dir


def _commit_sha(repo_dir: pathlib.Path) -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_dir, capture_output=True, text=True, check=True,
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


def _find_wlistdb(repo_dir: pathlib.Path) -> pathlib.Path | None:
    """Find the OFFIS test fixture directory, falling back to a search if the
    expected path has moved."""
    expected = repo_dir / WLISTDB_RELPATH
    if expected.exists():
        return expected
    # Fall back: look for any directory under dcmwlm/data containing .dump files
    data_dir = repo_dir / "dcmwlm" / "data"
    if data_dir.exists():
        for p in data_dir.rglob("*.dump"):
            return p.parent
    return None


def main() -> None:
    try:
        import pydicom  # noqa: F401
        from pydicom import dcmwrite
        from pydicom.dataset import FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    except ImportError:
        print("ERROR: pydicom not installed. Run: pip install pydicom pynetdicom", file=sys.stderr)
        sys.exit(1)

    out_dir = pathlib.Path(os.getenv("CRITCOM_DICOM_WORKLIST_DIR", "./orthanc-worklists"))
    cache_dir = pathlib.Path(os.getenv("CRITCOM_DCMTK_CACHE_DIR", "./.dcmtk-cache"))
    ref = os.getenv("CRITCOM_DCMTK_REF", "master")

    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    repo_dir = _ensure_dcmtk_clone(cache_dir, ref)
    sha = _commit_sha(repo_dir)
    log.info("seed_dicom_dcmtk.commit", sha=sha[:12])

    fixtures_dir = _find_wlistdb(repo_dir)
    if fixtures_dir is None:
        print(f"ERROR: could not find DCMTK fixtures under {repo_dir}/dcmwlm/data", file=sys.stderr)
        sys.exit(1)

    dump_files = sorted(fixtures_dir.glob("*.dump"))
    if not dump_files:
        print(f"ERROR: no .dump files found in {fixtures_dir}", file=sys.stderr)
        sys.exit(1)

    log.info("seed_dicom_dcmtk.fixtures_found", count=len(dump_files), dir=str(fixtures_dir))

    written: list[pathlib.Path] = []
    failed: list[tuple[str, str]] = []

    for dump_path in dump_files:
        try:
            ds = _parse_dump(dump_path.read_text())

            file_meta = FileMetaDataset()
            file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.31"  # MWL FIND
            file_meta.MediaStorageSOPInstanceUID = generate_uid()
            file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
            file_meta.ImplementationClassUID = generate_uid()
            ds.file_meta = file_meta
            ds.is_little_endian = True
            ds.is_implicit_VR = False

            out_path = out_dir / f"dcmtk-{dump_path.stem}.wl"
            dcmwrite(str(out_path), ds, write_like_original=False)
            written.append(out_path)
            log.info(
                "seed_dicom_dcmtk.wrote",
                file=out_path.name,
                patient=str(getattr(ds, "PatientName", "?")),
                priority=str(getattr(ds, "RequestedProcedurePriority", "?")),
            )
        except Exception as e:
            failed.append((dump_path.name, str(e)))
            log.warning("seed_dicom_dcmtk.failed", file=dump_path.name, error=str(e))

    print(f"\n✓ Converted {len(written)}/{len(dump_files)} DCMTK fixtures into {out_dir}/")
    print(f"  DCMTK ref: {ref}  commit: {sha[:12]}")
    print(f"  Cite as: DCMTK — OFFIS DICOM Toolkit. github.com/DCMTK/dcmtk @ {sha[:8]}")
    if written:
        print("\n  Written:")
        for p in written:
            print(f"    - {p.name}")
    if failed:
        print(f"\n  Failed ({len(failed)}):")
        for name, err in failed:
            print(f"    - {name}: {err}")
    print(
        "\nThese .wl files are picked up automatically by Orthanc when its"
        f"\nworklists volume is mounted at {out_dir.resolve()}."
    )


if __name__ == "__main__":
    main()
