import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
out = root / 'build/v6g-board-01'
def sha(path):
    return hashlib.sha256((root / path).read_bytes()).hexdigest()
def save(name, value):
    (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

backup = (out / 'before-flash-64k.bin').read_bytes()
assert len(backup) == 65536
assert hashlib.sha256(backup).hexdigest() == '95d3a11f8db843e362b2c59ed6fbf380dd630e067fa23f6ae5a9c7d2b11dff1e'
assert backup == (root / 'build/v6f-board-01/rollback-readback.bin').read_bytes()
assert backup.startswith((root / 'build/v5-fw-10/MotortesterV2-stream-candidate.bin').read_bytes())
image = 'build/v6g-fw-02/MotortesterV2-stream-candidate.bin'
elf = 'build/v6g-fw-02/MotortesterV2-stream-candidate.elf'
assert (root / image).stat().st_size == 37132
assert sha(image) == '8e8a5f2597a573ffaecfc054b01de726975ec5de07a33b06c4e56f5de75b3558'
assert sha(elf) == 'e8a9574fa7374492bdbe258685005b45f7230faf64276755e39c732693359946'
preflight = {
    'backup_bytes':len(backup), 'backup_sha256':hashlib.sha256(backup).hexdigest(),
    'whole_backup_equal_verified_S4':True, 'prefix_equal_V2S4':True,
    'candidate_bytes':37132, 'candidate_sha256':sha(image), 'candidate_elf_sha256':sha(elf),
    'probe':'ID=0', 'expected_sn':'57005400120000393333574E',
    'software_review':'docs/reviews/v2-06g-review.md',
    'software_review_sha256':sha('docs/reviews/v2-06g-review.md'),
    'software_archive_sha256':sha('docs/verification/v2-tx-prepare/software-evidence.json'),
    'source_commit':'a7b45bccf54f3155de03389aa5e49b237905c994',
    'source_frozen':True, 'no_G_flash_or_START_yet':True,
}
save('preflight.json', preflight)
plan = json.loads((root / 'build/v6e-board-01/plan.json').read_text(encoding='utf-8-sig'))
def rewrite(value):
    if isinstance(value,str):
        return value.replace('v6e-board-01','v6g-board-01').replace('v6e-fw-01','v6g-fw-02').replace('bab09184455a41ac9f552565c825ce83f029c40f',preflight['source_commit']).replace('0x56325338','0x56325341').replace('80a5ed8d064a2d0559f063d6650fb4edab078de4c233ea66ef2cb0e1ac62cf20',sha(image)).replace('0x8d18',hex(37132))
    if isinstance(value,list):return [rewrite(item) for item in value]
    if isinstance(value,dict):return {key:rewrite(item) for key,item in value.items()}
    return value
plan = rewrite(plan)
plan.update({
    'iteration':'V2-06g2', 'purpose':'One physical 100 kS/s trial of the independently reviewed TX preparation change',
    'source_commit':preflight['source_commit'], 'candidate_bytes':37132,
    'candidate_sha256':sha(image), 'candidate_elf_sha256':sha(elf),
    'preflight_sha256':sha('build/v6g-board-01/preflight.json'),
    'software_review_sha256':preflight['software_review_sha256'],
    'trial_tool_sha256':sha('host/tools/v2_stream_probe.py'),
    'single_START_only':True, 'target_record_seconds_after_preview':10,
    'physical_setup':'Previously confirmed: PA0 empty; board USB powered, ST-Link 3.3V disconnected; no wiring change requested',
    'readback_must_equal_before_reset_run':True,
    'post_flash_replug':'User board USB unplug/replug; ST-Link unchanged; app closed. Wait for actual ready reply.',
    'admission_before_START':{'build_id':'0x56325341','sample_rate_hz':100000,'channels':1,'adc_bits':12,'data_block_samples':128},
    'diagnostic_reads':2, 'profile_512_present':False,
    'diagnostic_decoder':'build/v6g-board-01/decode_diagnostics.py',
    'diagnostic_decoder_sha256':sha('build/v6g-board-01/decode_diagnostics.py'),
    'diagnostic_metric_change':'tx_max excludes prepare/encode; step/poll still include it. Never directly compare TX maxima with S8/S9 as total TX cost.',
    'acceptance':[
        'Program verify and independent byte-equal readback of all 37132 bytes',
        'Exact build/CAPS before one START; target Record 10 seconds after Preview; actual duration and overshoot preserved',
        'No source/host failure; record delta/host elapsed 90000..110000 samples/s is only a rough pacing check, not oscillator calibration',
        'Normal END reason0 and matching STOP ACK; unknown produced tail retained, not zero',
        'Fresh Open plus companion and exact selected raw compared to preserved wire, CRC/prefix/sequence validation',
        'COM owner closed before any SWD; two legacy136 dumps equal, expected build/nonce/generation, frozen, flags0, poll and copy below5120us',
        'TIM3 CEN0 PSC71 ARR9; ADC CR2=0 SMPR2 low3bits4; DMA EN0; relevant RCC clocks on/resets off; ADC_DR not read',
        'Independent physical review against these unchanged acceptance criteria; a failed trial stays failed'
    ],
    'failure_policy':'Preserve all traffic, prefix and diagnostics; no automatic second START or changed-Fs retry',
    'rollback_policy':{
        'automatic_after_failed_trial':False,
        'retain_candidate_if':'Board boots, communicates and acquisition is confirmed stopped, including a retained queue-full failure',
        'restore_only_if':['Programming/readback cannot be completed correctly','Candidate does not boot or USB communication remains unavailable after the planned replug','Source stopping cannot be confirmed','User needs ordinary verified 50 kS/s operation'],
        'record_reason_before_restore':True,
        'procedure':'Program fresh full64KiB backup with verify; independent whole readback byte comparison; reset/run then user replug; original READY helper without START',
        'user_instruction':'Do not restore old firmware every time if unnecessary'
    }
})
assert sha(plan['program_argv'][0]) == plan['cli_sha256']
assert sha(plan['rollback_ready_helper']) == plan['rollback_ready_helper_sha256']
save('plan.json',plan)
print(json.dumps({'preflight_sha256':sha('build/v6g-board-01/preflight.json'),'plan_sha256':sha('build/v6g-board-01/plan.json')},indent=2))
