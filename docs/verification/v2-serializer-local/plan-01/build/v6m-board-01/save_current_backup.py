"""Root: read the stopped board's current flash; never reset/program/open COM."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, subprocess, time

root = Path.cwd()
base = root / "build/v6m-board-01"
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
cli = Path("C:/Program Files (x86)/STMicroelectronics/STM32 ST-LINK Utility/ST-LINK Utility/ST-LINK_CLI.exe")
assert sha(cli) == "7fb012b5e26abf45342caa05c6bc33936f8a379b67797cc55658ffb8bf15e95f"
target = base / "before-flash-64k.bin"
assert not target.exists()
previous = json.loads((root / "build/v6l-board-01/150000/run/result.json").read_bytes())
assert previous["cleanup_finished"] and previous["final_state"]["phase"] == "closed"
argv = [str(cli), "-c", "ID=0", "SWD", "HOTPLUG", "-Dump", "0x08000000", "0x10000", str(target.relative_to(root))]
stamp = datetime.now(timezone.utc).isoformat()
start = time.monotonic()
result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
log = result.stdout.decode("utf-8", errors="replace")
(base / "backup.stdout.bin").write_bytes(result.stdout)
(base / "backup.log").write_text(log, encoding="utf-8")
(base / "backup-invocation.json").write_text(json.dumps({"argv": argv, "started_utc": stamp,
    "wall_seconds": time.monotonic()-start, "exit_code": result.returncode}, indent=2)+"\n", encoding="utf-8")
assert result.returncode == 0 and "57005400120000393333574E" in log and "succeded" in log, log
assert target.stat().st_size == 65536
prefix = target.read_bytes()[:42444]
assert hashlib.sha256(prefix).hexdigest() == "c1d2c5909341b010d0869f6f7a818d8dd46525bd18d6075e0dda780a9e23b9df"
record = {"status": "PASS", "bytes": 65536, "sha256": sha(target), "prefix_bytes": 42444,
    "prefix_sha256": hashlib.sha256(prefix).hexdigest(), "current_image": "V2SE/0x56325345",
    "user_confirmed": "Да, всё подключено, PA0 пуст, приложение закрыто",
    "operation": "Read flash only; no reset, programming or COM access"}
(base / "backup-verified.json").write_text(json.dumps(record, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
print(json.dumps(record, ensure_ascii=False))
