"""One offline actual-C DATA256/tail129 producer to Python-consumer check."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "host"))
from motortester.stream_wire import Kind, decode_frame, decode_payload

source = ROOT / sys.argv[1]
expected_sha256 = sys.argv[2]
output = ROOT / sys.argv[3]
content = source.read_bytes()
source_sha256 = hashlib.sha256(content).hexdigest()
assert source_sha256 == expected_sha256
assert content.endswith(b"\0")
encoded = [part + b"\0" for part in content.split(b"\0")[:-1]]
frames = [decode_frame(part, "device") for part in encoded]
assert [frame.kind for frame in frames] == [Kind.DATA, Kind.DATA, Kind.END]
assert [frame.sequence for frame in frames] == [4, 5, 6]
assert all(frame.revision == "0.3" and frame.nonce == 503 for frame in frames)
data = [decode_payload(frame) for frame in frames]
expected = tuple(((i * 37 + 3) & 4095) & 4092 for i in range(256))
expected += tuple((4095 - i) & 4092 for i in range(129))
assert [len(item.samples) for item in data[:2]] == [256, 129]
assert data[0].samples + data[1].samples == expected
assert (data[0].first_index, data[1].first_index) == (0, 256)
assert all(item.generation == 3 and item.config_id == 4 for item in data)
assert all(len(part) <= 371 for part in encoded)
raw = struct.pack("<385H", *expected)
assert data[2].prefix_end == 385 and data[2].prefix_crc32 == zlib.crc32(raw)
assert data[2].last_data_sequence == frames[1].sequence
assert source.read_bytes() == content
result = {
    "status": "PASS",
    "scope": "offline actual C generated synthetic wire; no physical evidence",
    "source": str(source.relative_to(ROOT)), "source_sha256": source_sha256,
    "source_unchanged": True,
    "decoder_sha256": hashlib.sha256((ROOT / "host/motortester/stream_wire.py").read_bytes()).hexdigest(),
    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "samples": 385, "raw_sha256": hashlib.sha256(raw).hexdigest(),
    "prefix_crc32": zlib.crc32(raw), "nonce": 503, "generation": 3, "config_id": 4,
    "wire_bytes": len(content), "frame_bytes": [len(part) for part in encoded],
    "DATA_counts": [256, 129], "frame_sequences": [frame.sequence for frame in frames],
    "END": {"reason": data[2].reason, "flags": data[2].flags,
            "produced_end": data[2].produced_end},
}
output.mkdir(exist_ok=True)
target = output / "c-producer-crosscheck.json"
assert not target.exists(), "Preserve existing evidence"
target.write_text(json.dumps(result, indent=2), "utf-8")
print(json.dumps(result, indent=2))
