"""One offline C-producer to Python-consumer packed DATA/prefix check."""
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "host"))
from motortester.stream_wire import Kind, decode_frame, decode_payload

source = ROOT / "build/v6i-native-01/packed-tail-transcript.bin"
content = source.read_bytes()
assert hashlib.sha256(content).hexdigest() == "5eb4a4f634e0e74e9cd86bb036f4c84486489260d2f13ed5163b9d7d570e99f8"
frames = [decode_frame(part + b"\0", "device") for part in content.split(b"\0")[:-1]]
assert [frame.kind for frame in frames] == [Kind.DATA, Kind.DATA, Kind.END]
assert all(frame.revision == "0.3" and frame.nonce == 503 for frame in frames)
data = [decode_payload(frame) for frame in frames]
expected = tuple(((i * 37 + 3) & 4095) & 4092 for i in range(128)) + (4092,) * 3
assert data[0].samples + data[1].samples == expected
assert (data[0].first_index, data[1].first_index) == (0, 128)
assert all(item.generation == 3 and item.config_id == 3 for item in data)
raw = struct.pack("<131H", *expected)
assert data[2].prefix_end == 131 and data[2].prefix_crc32 == zlib.crc32(raw)
assert data[2].last_data_sequence == frames[1].sequence
result = {"status": "PASS", "scope": "offline actual C generated synthetic wire; no physical evidence",
          "source": str(source.relative_to(ROOT)), "source_sha256": hashlib.sha256(content).hexdigest(),
          "decoder_sha256": hashlib.sha256((ROOT / "host/motortester/stream_wire.py").read_bytes()).hexdigest(),
          "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          "samples": 131, "raw_sha256": hashlib.sha256(raw).hexdigest(),
          "prefix_crc32": zlib.crc32(raw), "nonce": 503, "generation": 3, "config_id": 3,
          "wire_bytes": len(content), "frame_sequences": [frame.sequence for frame in frames]}
output = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "build/v6i-host-unit-03")
output.mkdir(exist_ok=True)
(output / "c-producer-crosscheck.json").write_text(json.dumps(result, indent=2), "utf-8")
print(json.dumps(result, indent=2))
