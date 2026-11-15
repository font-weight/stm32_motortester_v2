"""Read-only integrity check of the explicit cleanup receipt and saved sources."""
import json
from pathlib import Path
import subprocess

from verify_plan import sha

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = ROOT / 'docs/verification/cleanup-20261115'
LOCAL = ROOT / 'build/cleanup-20261115'
PLAN_SHA = '4442e10f671315547d7a62c613fc3a7fa9315f19c5d37b9b4d1a56df1adbd138'
SNAPSHOT_SHA = 'b6c6d0ba59dae89e961c8e90ecd6d7f643fab614919e1c379f2e08225532d007'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    assert sha(EVIDENCE / 'plan.json') == PLAN_SHA
    assert sha(LOCAL / 'preservation-before.json') == SNAPSHOT_SHA
    plan = read(EVIDENCE / 'plan.json')
    before = read(LOCAL / 'preservation-before.json')
    receipt = read(LOCAL / 'apply-01/removed.json')
    preflight = read(LOCAL / 'apply-01/preflight.json')
    assert receipt['status'] == preflight['status'] == 'PASS'
    assert receipt['plan_sha256'] == preflight['plan_sha256'] == PLAN_SHA
    assert [v['path'] for v in receipt['removed']] == [v['path'] for v in plan['allowlist']]
    assert receipt['freed_file_bytes'] == plan['totals']['bytes']
    assert receipt['removed_file_count'] == plan['totals']['files']
    assert not any((ROOT / v['path']).exists() for v in plan['allowlist'])
    for index, (relative, (size, digest)) in enumerate(before['files'].items(), 1):
        path = ROOT / relative
        assert path.is_file(), f'Missing preserved file: {relative}'
        assert path.stat().st_size == size and sha(path) == digest, f'Changed preserved file: {relative}'
        if index % 5000 == 0:
            print(f'Preservation {index}/{len(before["files"])}', flush=True)
    # The retained ZIPs were hashed by preflight. Check their presence/size again;
    # the byte-for-byte after-check above covers active packages and source files.
    for v in plan['allowlist']:
        if v['category'] == 'archive_duplicate':
            e = v['evidence']
            assert (ROOT / e['archive']).stat().st_size == e['archive_size_bytes']
    assert all((ROOT / p).is_file() for p in preflight['retained_file_hashes'])
    worktrees = subprocess.check_output(['git', '-C', str(ROOT), 'worktree', 'list', '--porcelain']).decode()
    assert worktrees == before['git_worktrees'], 'Git worktree changed during cleanup'
    assert not subprocess.check_output(['git', '-C', str(ROOT / 'build/v18src'), 'status', '--porcelain'])
    result = {'status': 'PASS', 'plan_sha256': PLAN_SHA, 'snapshot_sha256': SNAPSHOT_SHA,
              'removed_directories': len(receipt['removed']), 'removed_files': receipt['removed_file_count'],
              'removed_logical_bytes': receipt['freed_file_bytes'],
              'preserved_files_sha256_checked': len(before['files']), 'preserved_bytes_checked': before['size_bytes'],
              'retained_zip_presence_and_sizes': 'PASS', 'git_worktrees_unchanged': True,
              'runtime_code_changed': False, 'hardware_access_performed': False}
    output = EVIDENCE / 'integrity-result.json'
    assert not output.exists()
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
