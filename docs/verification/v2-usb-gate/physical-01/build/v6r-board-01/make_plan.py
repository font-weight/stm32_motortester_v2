"""Prepare the exact R/SK diagnostic trial plan; no hardware access."""
from pathlib import Path
import hashlib, json, re, subprocess

r = Path.cwd()
base = r / 'build/v6r-board-01'
fw = r / 'build/v6r-fw-02'
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
p = json.loads((r / 'build/v6q-board-01/plan.json').read_bytes())
review_path = r / 'docs/verification/v2-usb-gate/critic-source.json'
review = json.loads(review_path.read_bytes())
assert review['status'] == 'PASS' and review['score'] >= 9.5
receipt = json.loads((fw / 'receipt.json').read_bytes())
assert receipt['status'] == 'BUILT_STATIC_CHECKED_TRANSPORT_CANDIDATE'
assert receipt['config']['firmware_build'] == 0x5632534b
source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
image = fw / 'MotortesterV2-stream-candidate.bin'
elf = fw / 'MotortesterV2-stream-candidate.elf'
nm = fw / 'image.nm'
backup = json.loads((base / 'backup-verified.json').read_bytes())
assert backup['status'] == 'PASS'
assert sha(base / 'before-flash-64k.bin') == backup['sha256']
assert backup['prefix_bytes'] == 45372
assert backup['prefix_sha256'] == '5041ae67ccc25eda8d0003121370baed1120b025399099d4c3f42abfee61ca88'
symbols = nm.read_text('utf-8')

def address(name, size):
    matches = re.findall(r'^([0-9a-fA-F]+)\s+' + f'{size:08x}' +
                         r'\s+B\s+' + name + r'\s*$', symbols, re.M)
    assert len(matches) == 1, name
    return '0x' + matches[0].upper()

p.update(
    schema='motortester-v2-usb-gate-physical-plan-1',
    status='ROOT_REVIEWED_AWAITING_INDEPENDENT_EXACT_ADMISSION',
    purpose='One exact SK flash/readback and one150k DATA1024 requested30s diagnostic trial. Preserve first-close gate24 plus64/136, wire/raw/CRC/Open/Stop and every failed result. A valid diagnostic does not meet the still-open sustained150k requirement. No50/100, automatic retry or rollback.',
    source_commit=source,
    candidate_path=image.relative_to(r).as_posix(), candidate_bytes=image.stat().st_size,
    candidate_sha256=sha(image), candidate_elf_sha256=sha(elf), candidate_nm_sha256=sha(nm),
    firmware_build='0x5632534b', diagnostic_address=address('mt_stream_diagnostics', 136),
    progress_address=address('mt_stream_progress', 64), progress_bytes=64,
    gate_address=address('mt_usb_gate', 24), gate_bytes=24,
    rollback_image='build/v6r-board-01/before-flash-64k.bin', rollback_sha256=backup['sha256'],
    expected_pnp_id='USB\\VID_1209&PID_0001&MI_00\\6&D2DE68C&0&0000')
for key in list(p):
    if key.startswith('backup_expected_'):
        del p[key]
p['backup_expected_SJ_prefix_bytes'] = 45372
p['backup_expected_SJ_prefix_sha256'] = backup['prefix_sha256']
p['before_flash'] = [
    'Exact R/SK contract, source, actual-C gate/progress, decoder and ARM/resource review PASS>=9.5; P1-M2-01 sustained150k remains open.',
    'Fresh expected ST-Link/COM6 identity and no application/capture owner. User confirmed PA0 empty, board powered only by its USB; unchanged low-voltage setup.',
    'Fresh64KiB current SJ backup verified against known45372byte prefix; preserve all previous evidence.',
    'Final plan pins image, backup, helpers, unchanged host capture and previous Windows package; independent exact plan admission before Flash.']
p['flash_procedure'] = [
    'Root only: one program/verify, then independent full candidate readback with every byte equal.',
    'One Reset/Run only after equality; then require a new actual user cold power cycle of both board USB and ST-Link USB: off10s, board USB on first, ST-Link5s later. Do not alter wiring; PA0 empty, application closed. This follows the observed Q2 enumeration recovery, not a proved cause or firmware fix.',
    'Do not restore older firmware merely because this diagnostic acquisition reports queue-full.']
p['session_rules'] = [
    'One START after fresh boot/replug. Discovery0.2 then fresh nonce HELLO0.3 mode5; exactSKbuild/CAPS before START.',
    'Existing probe requests30s Record; preserve earlyFAIL, traffic, journal and companion without padding or concealed gaps.',
    'No SWD/halt during activeCOM. After closedowner, offline verify END/ACK/nonce/gen/CRC/indices/raw; only coherent terminal evidence permits root_read_closed.',
    'Read legacy136 twice, progress64 twice, gate24 twice, then stopped TIM3/ADC/DMA/RCC. Never read ADC_DR. Decode against exact SK/image/nonce/gen.',
    'Gate24 describes last evaluated applicable episode before N CLOSING. Later64 USB held snapshot is not simultaneous and cannot prove sameepisode, even if held=1.',
    'Distinguish historical, invalidated, unknown, CAP, noactive, invalidclock and saturated observations. CAP before a later fault does not explain that later fault.',
    'On failure finish this plan, preserve evidence and installed SK if stop/link permit; no repeated START, softwareReset, automatic rollback or50/100.',
    'Diagnostic acceptance requires trustworthy identity/freeze/evaluatedbranch with explicit applicability limits. Stable150k separately requires full30s without sourcefault/gap, matching raw/CRC/Open/END/ACK and stopped registers. Instrumentation may affect timing; not analog qualification.']
s = p['sessions'][0]
assert s['sample_rate_hz'] == 150000
s.update(seconds=30, directory='build/v6r-board-01/150000', START_limit=1,
         fresh_Reset_Run_and_actual_user_replug_required=True)
s['trial_argv'] = ['.venv/Scripts/python.exe', '-B', 'host/tools/v2_stream_probe.py',
    '--port', 'COM6', '--output', s['directory'] + '/run', '--seconds', '30',
    '--build-id', '0x5632534b', '--sample-rate', '150000',
    '--source-commit', source, '--image-sha256', sha(image)]
p['sessions'] = [s]
p['software_review'] = dict(path=review_path.relative_to(r).as_posix(),
                            sha256=sha(review_path), score=review['score'])
p['windows_package']['reused_from_L'] = True
p['windows_package']['reason'] = 'UI/wire/capture unchanged; new host tools only decode saved diagnostic banks offline. Existing Windows acceptance is separate.'
inputs = {k: v for k, v in p['execution_inputs'].items()
          if k.startswith('host/') or k.startswith('build/v6lw1/')}
paths = [image, elf, nm, fw / 'static-bound.json', r / 'build/v6r-freeze.json',
         review_path, base / 'backup-verified.json', base / 'before-flash-64k.bin',
         r / 'host/tools/decode_stream_progress.py', r / 'host/tools/decode_usb_gate.py']
paths += [base / name for name in ('program_and_verify.py', 'analyze_physical.py',
    'decode_diagnostics.py', 'save_stopped_state.py', 'root_read_closed.py', 'run_trial.py')]
for path in paths:
    inputs[path.relative_to(r).as_posix()] = sha(path)
for name, digest in inputs.items():
    assert sha(r / name) == digest, name
p['execution_inputs'] = inputs
p['program_argv'] = [p['cli_path'], '-c', 'ID=0', 'SWD', 'HOTPLUG',
                     '-P', p['candidate_path'], '0x08000000', '-V']
p['readback_argv'] = [p['cli_path'], '-c', 'ID=0', 'SWD', 'HOTPLUG', '-Dump',
    '0x08000000', hex(p['candidate_bytes']), 'build/v6r-board-01/readback.bin']
with (base / 'plan.json').open('x', encoding='utf-8') as f:
    json.dump(p, f, ensure_ascii=False, indent=2)
    f.write('\n')
print(json.dumps(dict(plan_sha256=sha(base / 'plan.json'), source=source,
    bytes=p['candidate_bytes'], image_sha256=p['candidate_sha256'],
    legacy_address=p['diagnostic_address'], progress_address=p['progress_address'],
    gate_address=p['gate_address'])))
