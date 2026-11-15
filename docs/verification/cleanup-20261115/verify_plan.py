"""Read-only preflight for this dated cleanup; never deletes or moves files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def overlap(a, b):
    a, b = str(a).casefold().rstrip('\\/'), str(b).casefold().rstrip('\\/')
    return a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep)


def inspect(root, hashes=False):
    files, stack = {}, [root]
    while stack:
        base = stack.pop()
        for child in base.iterdir():
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError(f'Reparse/symlink: {child}')
            if child.name == '.git':
                raise ValueError(f'Nested Git data: {child}')
            if child.is_dir():
                stack.append(child)
            elif child.is_file():
                files[child.relative_to(root).as_posix()] = [info.st_size, sha(child) if hashes else None]
            else:
                raise ValueError(f'Unexpected filesystem entry: {child}')
    return files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('plan', type=Path)
    parser.add_argument('expected_sha')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if sha(args.plan) != args.expected_sha:
        raise ValueError('Plan hash mismatch')
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    if Path(plan['workspace']).resolve(strict=True) != root:
        raise ValueError('Workspace mismatch')

    def inside(relative):
        rel = Path(relative)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError(f'Not a relative child: {relative}')
        lexical = root / rel
        cursor = lexical
        while cursor != root:
            info = cursor.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError(f'Reparse ancestor: {cursor}')
            cursor = cursor.parent
        result = lexical.resolve(strict=True)
        if result == root or root not in result.parents:
            raise ValueError(f'Outside workspace: {relative}')
        return result

    protected = [inside(p) for p in plan['protected_roots']]
    worktrees = subprocess.check_output(['git', '-C', str(root), 'worktree', 'list', '--porcelain']).decode('utf-8')
    protected += [Path(line[9:]).resolve(strict=True) for line in worktrees.splitlines()
                  if line.startswith('worktree ') and Path(line[9:]).resolve(strict=True) != root]
    tracked = [root / p for p in subprocess.check_output(
        ['git', '-C', str(root), 'ls-files', '-z']).decode('utf-8').split('\0') if p]
    targets = [inside(e['path']) for e in plan['allowlist']]
    for i, target in enumerate(targets):
        if any(overlap(target, p) for p in protected + targets[:i]):
            raise ValueError(f'Protected/overlapping target: {target}')
        if any(overlap(target, p) for p in tracked):
            raise ValueError(f'Tracked files below target: {target}')

    retained_hashes = {}

    def retained(relative, expected=None):
        p = inside(relative)
        if any(overlap(p, target) for target in targets):
            raise ValueError(f'Recovery material would be deleted: {p}')
        if expected is not None:
            if p not in retained_hashes:
                retained_hashes[p] = sha(p)
            if retained_hashes[p] != expected:
                raise ValueError(f'Retained file hash differs: {p}')
        return p

    checked = []
    for index, (entry, target) in enumerate(zip(plan['allowlist'], targets), 1):
        category, evidence = entry['category'], entry.get('evidence', {})
        parts = Path(entry['path']).parts
        expected_leaf = {'reproducible_venv': 'venv', 'duplicate_wheelhouse': 'wheelhouse',
                         'generated_pyinstaller': 'pyinstaller'}
        if category in expected_leaf:
            if len(parts) != 3 or parts[0] != 'build' or not parts[1].startswith('v') or parts[2] != expected_leaf[category]:
                raise ValueError(f'Unexpected generated path: {entry["path"]}')
        elif category == 'archive_duplicate':
            if len(parts) != 3 or parts[0] != 'build' or not parts[1].startswith('v') or parts[2] not in ('dist', 'Проверка переноса'):
                raise ValueError(f'Unexpected archive duplicate: {entry["path"]}')
        elif category == 'python_cache':
            if entry['path'] not in plan['explicit_cache_paths'] or parts[-1] != '__pycache__':
                raise ValueError('Unexpected Python cache')
        elif category == 'compiler_cache':
            if entry['path'] != 'docs/verification/v2-serializer-local/production-01/build/v6m-native-01/zig-global':
                raise ValueError('Unexpected compiler cache')
        else:
            raise ValueError(f'Unknown cleanup category: {category}')
        files = inspect(target, hashes=category in ('archive_duplicate', 'duplicate_wheelhouse'))
        size = sum(v[0] for v in files.values())
        if len(files) != entry['file_count'] or size != entry['size_bytes']:
            raise ValueError(f'Target composition changed: {target}')
        if category == 'archive_duplicate':
            retained(evidence['archive'], evidence['archive_sha256'])
            digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
            if digest != evidence['content_manifest_sha256']:
                raise ValueError(f'Unmatched package content: {target}')
        elif category == 'duplicate_wheelhouse':
            expected = {v['path']: [v['size_bytes'], v['sha256']] for v in evidence['matches']}
            if files != expected:
                raise ValueError(f'Unmatched wheels: {target}')
            for v in evidence['matches']:
                retained(v['retained_path'], v['sha256'])
        elif category == 'reproducible_venv':
            if sha(inside(evidence['pyvenv_cfg'])) != evidence['pyvenv_cfg_sha256']:
                raise ValueError(f'Changed venv configuration: {target}')
            if not (target / 'Scripts/python.exe').is_file() or any(
                    not (target / 'Lib/site-packages' / p).is_dir() for p in evidence['expected_site_packages']):
                raise ValueError(f'Unexpected venv structure: {target}')
            retained(evidence['retained_environment'])
        elif category == 'generated_pyinstaller':
            for p in evidence['retained_files']:
                retained(p)
            for item in evidence.get('retained_diagnostics', []):
                retained(item['retained_path'], item['sha256'])
        elif category == 'python_cache' and any(Path(p).suffix not in ('.pyc', '.pyo') for p in files):
            raise ValueError(f'Non-bytecode data in cache: {target}')
        checked.append({'path': entry['path'], 'absolute_path': str(target), 'category': category,
                        'file_count': len(files), 'size_bytes': size})
        if index % 40 == 0:
            print(f'Preflight {index}/{len(targets)}', flush=True)
    receipt = {'status': 'PASS', 'deletions_performed': False, 'plan_sha256': args.expected_sha,
               'workspace': str(root), 'targets': checked,
               'retained_file_hashes': {str(p.relative_to(root)): h for p, h in retained_hashes.items()}}
    if args.output.exists():
        raise ValueError('Preflight receipt already exists')
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Preflight PASS: {len(checked)} directories, {sum(e["size_bytes"] for e in checked)} bytes')


if __name__ == '__main__':
    main()
