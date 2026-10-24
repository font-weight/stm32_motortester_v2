"""Derive an optional SA-only READY helper; do not execute it or open COM."""
from pathlib import Path
import hashlib
root=Path(__file__).resolve().parents[1]
p=root/'build/v5-board-stream-04/check_ready.py';src=p.read_text(encoding='utf-8')
assert hashlib.sha256(p.read_bytes()).hexdigest()=='7034811bb771781927228b5115e7446ef3ec9b059963cbc7963a07fbe48f7c34'
changes={
    'V2S4':'V2SA',
    '0x56325334':'0x56325341',
    'c10884fa39ad1a10ce0fcfc9d6e17f170e1e0bf0':'a7b45bccf54f3155de03389aa5e49b237905c994',
    '04ba2853b6a964cd812bf555a32da7fb019bcd60ba9fda0bd586d71112b3143d':'8e8a5f2597a573ffaecfc054b01de726975ec5de07a33b06c4e56f5de75b3558',
    'and bridge.connection.execution_kind == "physical")':'and bridge.connection.execution_kind == "physical"\n                and tuple(bridge.connection.observed_caps) == (1,1,0,12,100000,1,128,1))'
}
for a,b in changes.items():
    assert a in src;src=src.replace(a,b)
compile(src,'check_sa_ready.py','exec')
target=root/'build/v6h-board-01/check_sa_ready.py'
assert not target.exists()
target.write_text(src,encoding='utf-8',newline='\n')
print(hashlib.sha256(target.read_bytes()).hexdigest())
