"""Prepare one bounded profiling trial; no device access or stream qualification."""
import hashlib
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
folder = root / 'build/v6f-board-01'
fw = root / 'build/v6f-fw-03'
sha = lambda raw: hashlib.sha256(raw).hexdigest()
backup = (folder / 'before-flash-64k.bin').read_bytes()
assert len(backup) == 65536
assert sha(backup) == '95d3a11f8db843e362b2c59ed6fbf380dd630e067fa23f6ae5a9c7d2b11dff1e'
assert backup == (root / 'build/v6e-board-01/rollback-readback.bin').read_bytes()
s4 = (root / 'build/v5-fw-10/MotortesterV2-stream-candidate.bin').read_bytes()
assert backup[:len(s4)] == s4
receipt = json.loads((fw/'receipt.json').read_text('utf8'))
assert receipt['config']['firmware_build'] == 0x56325339
image = (fw/'MotortesterV2-stream-candidate.bin').read_bytes()
elf = (fw/'MotortesterV2-stream-candidate.elf').read_bytes()
assert sha(image) == receipt['artifacts']['MotortesterV2-stream-candidate.bin']
assert sha(elf) == receipt['artifacts']['MotortesterV2-stream-candidate.elf']
source = subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()

def save(name,value):
    target=folder/name
    assert not target.exists(), target
    target.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf8')

pre=dict(backup_bytes=len(backup),backup_sha256=sha(backup),whole_backup_equal_verified_S4=True,
         prefix_equal_V2S4=True,candidate_bytes=len(image),candidate_sha256=sha(image),
         candidate_elf_sha256=sha(elf),probe='ID=0',expected_sn='57005400120000393333574E')
save('preflight.json',pre)
plan=json.loads((root/'build/v6e-board-01/plan.json').read_text('utf8'))
plan=json.loads(json.dumps(plan).replace('v6e-board-01','v6f-board-01').replace('v6e-fw-01','v6f-fw-03'))
plan['base_commit']=source
plan['preflight_sha256']=sha((folder/'preflight.json').read_bytes())
plan['readback_argv'][plan['readback_argv'].index('-Dump')+2]=hex(len(image))
args=plan['trial_argv']
for option,value in [('--seconds','1'),('--build-id','0x56325339'),('--source-commit',source),('--image-sha256',sha(image))]:
    args[args.index(option)+1]=value
plan['candidate_bytes']=len(image)
plan['candidate_elf_sha256']=sha(elf)
plan.pop('observed_rate_tolerance')
plan.update(scope='One diagnostic run only; not 100k or 200k stream qualification',
            profile_address='0x20002C4C',profile_bytes=512,profile_target_cycles=18000000,
            profile_target_ms_nominal=250,profile_dump_copies=2,legacy_dump_copies=2,
            rollback_always=True,maximum_starts=1,
            hardware_unchanged='PA0 empty; USB board power; ST-Link 3.3V disconnected',
            replug_requires_user_reply=True,
            profile_acceptance=[
                'Exact BIN program verify plus independent byte-equal readback before Reset/Run',
                'Expected COM6, build and CAPS checked before the single START',
                'Serial owner closed before all SWD reads',
                'Two identical frozen512 records; exact build/nonce/generation/epoch and pinned ABI',
                'Old136 records paired; DWT validity and first-cause metadata checked',
                'Source fault remains physical trial failure; diagnostic integrity is independent',
                'Observer estimate heuristic only; saturation or invalid metadata blocks attribution',
                '250ms target may overshoot; use actual boundaries and exclude Stop/drain',
                'TIME/USB ISR/STEP overlap; never add as independent CPU shares',
                'Restore entire fresh64KiB S4, byte verify, Reset/Run, user replug and READY without START'])
save('plan.json',plan)
decoder=(root/'build/v6e-board-01/decode_diagnostics.py').read_text('utf8')
for before,after in [('V2S8','V2S9'),('0x56325338','0x56325339'),
    ('80a5ed8d064a2d0559f063d6650fb4edab078de4c233ea66ef2cb0e1ac62cf20',sha(image)),
    ('65d477b3cfae09d3bc9c05fe7a2fa2c498445b22dac9f79a2c89b1b0e5e6330e',sha(elf))]:
    assert before in decoder,before
    decoder=decoder.replace(before,after)
target=folder/'decode_diagnostics.py'
assert not target.exists()
target.write_text(decoder,encoding='utf8')
save('decoder-inputs.json',{'legacy_decoder_sha256':sha(target.read_bytes()),
    'profile_decoder_path':'build/v6f-decoder/decode_profile.py',
    'profile_decoder_sha256':sha((root/'build/v6f-decoder/decode_profile.py').read_bytes()),
    'profile_header_sha256':sha((root/'firmware/v2-stream/profile/mt_stream_profile.h').read_bytes()),
    'profile_abi_sha256':sha((root/'firmware/v2-stream/profile/ABI.md').read_bytes())})
print(json.dumps({'plan_sha256':sha((folder/'plan.json').read_bytes()),'source_commit':source,'preflight':pre}))
