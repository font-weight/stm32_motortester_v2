"""Freeze one S8 trial plan from the earlier reviewed S7 plan; no hardware IO."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
folder = root / 'build/v6e-board-01'
sha = lambda data: hashlib.sha256(data).hexdigest()
backup = (folder / 'before-flash-64k.bin').read_bytes()
assert len(backup) == 65536
assert sha(backup) == '95d3a11f8db843e362b2c59ed6fbf380dd630e067fa23f6ae5a9c7d2b11dff1e'
assert backup == (root / 'build/v6d-board-01/rollback-readback.bin').read_bytes()
s4 = (root / 'build/v5-fw-10/MotortesterV2-stream-candidate.bin').read_bytes()
assert backup[:len(s4)] == s4
image = (root / 'build/v6e-fw-01/MotortesterV2-stream-candidate.bin').read_bytes()
assert len(image) == 36120
assert sha(image) == '80a5ed8d064a2d0559f063d6650fb4edab078de4c233ea66ef2cb0e1ac62cf20'
source = 'bab09184455a41ac9f552565c825ce83f029c40f'
def save(name, value):
    path = folder / name
    assert not path.exists(), path
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
pre = dict(backup_bytes=len(backup), backup_sha256=sha(backup),
           whole_backup_equal_verified_S4=True, prefix_equal_V2S4=True,
           candidate_bytes=len(image), candidate_sha256=sha(image),
           probe='ID=0', expected_sn='57005400120000393333574E')
save('preflight.json', pre)
old = root / 'build/v6d-board-01'
plan_text = (old / 'plan.json').read_text('utf-8')
for before, after in [('v6d-board-01', 'v6e-board-01'), ('v6d-fw-01', 'v6e-fw-01'),
        ('3665be41e80c8168ad97c61d64cb79b232091d03', source),
        ('0x56325337', '0x56325338'), ('0x8da4', '0x8d18'),
        ('f3d5563139d4e5892273312996bd8b8486f222196e6cf3c25042d5c37c6a290b', sha(image))]:
    assert before in plan_text, before
    plan_text = plan_text.replace(before, after)
plan = json.loads(plan_text)
plan['candidate_bytes'] = len(image)
plan['preflight_sha256'] = sha((folder / 'preflight.json').read_bytes())
plan['rollback_ready_helper'] = 'build/v5-board-stream-04/check_ready.py'
plan['rollback_ready_argv'] = ['.venv/Scripts/python.exe', '-B', plan['rollback_ready_helper'], '--output', 'build/v6e-board-01/rollback-ready.json']
plan['rollback_ready_env'] = {'PYTHONPATH': 'host'}
plan['rollback_ready_helper_sha256'] = '7034811bb771781927228b5115e7446ef3ec9b059963cbc7963a07fbe48f7c34'
save('plan.json', plan)
decoder = (old / 'decode_diagnostics.py').read_text('utf-8')
for before, after in [('V2S7','V2S8'), ('0x56325337','0x56325338'),
        ('f3d5563139d4e5892273312996bd8b8486f222196e6cf3c25042d5c37c6a290b', sha(image)),
        ('5bc0eb99bf0490c3ef98ecea28e6d0dd3b006782d6719f02e59e3f858346aa25',
         '65d477b3cfae09d3bc9c05fe7a2fa2c498445b22dac9f79a2c89b1b0e5e6330e')]:
    assert before in decoder, before
    decoder = decoder.replace(before, after)
path = folder / 'decode_diagnostics.py'
assert not path.exists()
path.write_text(decoder, encoding='utf-8')
print(json.dumps({'preflight': pre, 'plan_sha256': sha((folder/'plan.json').read_bytes()),
                  'decoder_sha256': sha(path.read_bytes())}, indent=2))
