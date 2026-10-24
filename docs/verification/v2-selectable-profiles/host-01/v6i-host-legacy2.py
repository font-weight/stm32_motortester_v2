"""One read-only reopen of H2's unchanged real legacy2 journal+companion2."""
import hashlib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "host"))
from motortester.v2.stream_files import open_stream

path = ROOT / "build/v6h-board-01/run/physical.mtstream"
sidecar = path.with_name(path.name + ".v2.json")
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
before = {str(p.relative_to(ROOT)): digest(p) for p in (path, sidecar)}
assert path.read_bytes()[:8] == b"MTSTRM\x02\x00"
assert json.loads(sidecar.read_text("utf-8"))["format_version"] == 2
context, attempt = open_stream(path)
recording = attempt.recording
assert recording is not None and attempt.recovery_issue is None and context.companion_present
assert recording.identity.nominal_fs_hz == 100_000 and recording.identity.retained_bits == 12
assert recording.identity.acquisition_mode == 0 and recording.identity.protocol_revision == "0.2-draft-081721"
assert context.connection.observed_caps == (1, 1, 0, 12, 100_000, 1, 128, 1)
after = {str(p.relative_to(ROOT)): digest(p) for p in (path, sidecar)}
assert before == after
result = {"status": "PASS", "scope": "single offline legacy2/companion2 reopen; no new physical evidence",
          "before": before, "after": after, "originals_unchanged": True,
          "source_journal_magic": 2, "source_companion_version": 2,
          "retained_bits_in_memory": recording.identity.retained_bits,
          "first": recording.first_sample_index, "end": recording.end_sample_index,
          "samples": recording.end_sample_index - recording.first_sample_index,
          "companion_verified": context.companion_present,
          "script_sha256": digest(Path(__file__))}
output = ROOT / "build/v6i-host-unit-03"
output.mkdir(exist_ok=True)
(output / "legacy2-open.json").write_text(json.dumps(result, indent=2), "utf-8")
print(json.dumps(result, indent=2))
