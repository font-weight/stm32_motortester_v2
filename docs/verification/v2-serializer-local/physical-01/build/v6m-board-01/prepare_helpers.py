"""Prepare M helper copies without running hardware or altering L evidence."""
from pathlib import Path
import hashlib, json
r = Path.cwd()
old = r / "build/v6l-board-01"
new = r / "build/v6m-board-01"
names = ("program_and_verify.py", "analyze_physical.py", "decode_diagnostics.py",
         "save_stopped_state.py", "root_read_stopped.py", "root_read_fault.py")
rows = []
for name in names:
    source = old / name
    text = source.read_text("utf-8")
    text = text.replace("build/v6l-board-01", "build/v6m-board-01")
    text = text.replace("docs/verification/v2-batch1024/critic-flash.json", "docs/verification/v2-serializer-local/critic-flash.json")
    text = text.replace("V2SE", "V2SF").replace("v2se", "v2sf").replace("0x56325345", "0x56325346")
    text = text.replace("SE trial", "SF trial").replace("user_confirmed_SE_replug", "user_confirmed_SF_replug")
    target = new / name
    with target.open("x", encoding="utf-8", newline="\n") as f:
        f.write(text)
    rows.append({"source":source.relative_to(r).as_posix(),
                 "source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
                 "target":target.relative_to(r).as_posix(),
                 "target_sha256":hashlib.sha256(target.read_bytes()).hexdigest()})
(new / "helper-derivation.json").write_text(json.dumps({"scope":"Plan-local copies; no hardware called",
    "changes":"Base path, review path and build label/id only", "files":rows}, indent=2)+"\n", encoding="utf-8")
print(json.dumps({"copied_helpers":len(rows),"hardware_access":False}))
