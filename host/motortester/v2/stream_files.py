"""Bounded, worker-only V2 stream reads and raw CSV export."""
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import struct

from ..stream_recording import ATTEMPT_MAGIC, recover, recover_attempt
from .stream_device import open_verified_context


def open_stream(path):
    path = Path(path)
    context = open_verified_context(path)
    with path.open("rb") as stream:
        attempt = stream.read(8) == ATTEMPT_MAGIC
    archive = recover_attempt(path) if attempt else recover(path)
    return context, archive


def export_stream(path, recording, context):
    """Export all verified raw in chunks; no invented volts or gap filling.

    Exclusive creation protects existing files. If disk/read fails, the CSV
    prefix and complete=false receipt remain available for inspection.
    """
    path = Path(path)
    sidecar = path.with_name(path.name + ".json")
    metadata = {
        "format": "motortester-v2-stream-csv", "format_version": 1,
        "complete": False, "context": asdict(context.context),
        "source_companion_present": context.companion_present,
        "source_journal_sha256": context.journal_sha256,
        "identity": asdict(recording.identity),
        "first_sample_index": recording.first_sample_index,
        "end_sample_index": recording.end_sample_index,
        "time_basis": "nominal_unverified",
        "terminal": None if recording.terminal is None else asdict(recording.terminal),
        "recovery_issue": recording.recovery_issue,
        "discarded_tail_bytes": recording.discarded_tail_bytes,
    }
    # Reserve both names before writing samples. A pre-existing counterpart is
    # never replaced, even when another application creates it concurrently.
    with path.open("x", encoding="utf-8", newline="") as stream, \
            sidecar.open("x", encoding="utf-8") as receipt:
        json.dump(metadata, receipt, ensure_ascii=False, indent=2, allow_nan=False)
        receipt.flush()
        writer = csv.writer(stream)
        writer.writerow(("sample_index", "time_from_recording_start_s", "adc_code"))
        for block in recording.iter_raw():
            for offset, (code,) in enumerate(struct.iter_unpack("<H", block.raw_u16le)):
                index = block.first_sample_index + offset
                writer.writerow((index, (index - recording.first_sample_index) /
                                 recording.identity.nominal_fs_hz, code))
        stream.flush()
        digest = hashlib.sha256()
        with path.open("rb") as raw:
            for chunk in iter(lambda: raw.read(256 * 1024), b""):
                digest.update(chunk)
        metadata.update(complete=True, csv_sha256=digest.hexdigest())
        # Finish through the descriptor we reserved, never replace another
        # file that appeared at the sidecar path during the export.
        receipt.seek(0)
        json.dump(metadata, receipt, ensure_ascii=False, indent=2, allow_nan=False)
        receipt.truncate()
    return str(path)
