#!/usr/bin/env python3
"""Source + Markdown handoff only; no measurements, images or compiled artifacts."""
import argparse
import datetime as dt
import hashlib
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def git(source, *args):
    return subprocess.run(['git', '-C', str(source), *args], check=True, capture_output=True).stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'deliverables/ai-ran-source-handoff-20261108.zip')
    parser.add_argument('--vendor-root', type=Path, default=Path('/home/cindy2/oran-lab'))
    args = parser.parse_args()
    payload = {}
    for name in ['README.md', 'START_HERE.md', 'GPU_HANDOFF_PLAN.md', 'requirements-study.txt', '.gitignore']:
        payload[name] = (ROOT / name).read_bytes()
    for directory in ['scripts', 'analysis', 'workloads', 'configs', 'tests', 'docs']:
        for path in sorted((ROOT / directory).rglob('*')):
            if not path.is_file() or '__pycache__' in path.parts:
                continue
            allowed = {'.md', '.patch'} if directory == 'docs' else {'.py', '.sh', '.yml', '.yaml', '.csv'}
            if path.suffix in allowed or path.name == 'srsran-LICENSE':
                payload[str(path.relative_to(ROOT))] = path.read_bytes()
    # Keep report prose only; CSVs, PNGs, raw records and previous ZIPs stay out.
    for path in sorted((ROOT / 'deliverables').glob('*.md')):
        payload[str(path.relative_to(ROOT))] = path.read_bytes()
    sessions = sorted((ROOT / 'results/processed').glob('remote-session-*/status.json'))
    if sessions:
        for path in sessions[-1].parent.glob('*.md'):
            payload['reports/latest-session/' + path.name] = path.read_bytes()
    provenance = ['# Source provenance', '', 'Created UTC: ' + dt.datetime.now(dt.timezone.utc).isoformat(),
                  '', 'This package contains current worktree content, including uncommitted handoff updates.',
                  'No experiment raw data, aggregate CSVs, plots, binaries, build products or Git metadata.',
                  'Upstream source test fixtures are not experimental measurements.', '']
    try:
        provenance += ['Project base commit: `' + git(ROOT, 'rev-parse', 'HEAD').decode().strip() + '`', '']
    except subprocess.CalledProcessError:
        provenance += ['Project Git revision unavailable; preserve this source snapshot.', '']
    excluded = {'.o', '.a', '.so', '.dll', '.exe', '.pyc', '.zip', '.gz', '.xz', '.bz2', '.7z',
                '.png', '.jpg', '.jpeg', '.gif', '.pdf', '.pcap', '.db', '.sqlite', '.log', '.pem', '.key'}
    for name in ['srsRAN_Project', 'flexric']:
        source = args.vendor_root / name
        revision = git(source, 'rev-parse', 'HEAD').decode().strip()
        status = git(source, 'status', '--short', '--untracked-files=no').decode().strip()
        count = 0
        for raw in git(source, 'ls-files', '-z').split(b'\0'):
            if not raw:
                continue
            relative = Path(raw.decode())
            if relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Unsafe vendor path')
            if any(part in {'.git', 'build', '__pycache__', '.venv'} for part in relative.parts):
                continue
            path = source / relative
            if path.suffix.lower() in excluded or path.name.startswith('.env'):
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f'Unresolved source entry: {name}/{relative}')
            data = path.read_bytes()
            if data.startswith(b'\x7fELF'):
                continue
            if name == 'srsRAN_Project' and str(relative) == 'apps/services/worker_manager/worker_manager.cpp':
                text = data.decode()
                needle = '    nof_workers = worker_cfg.nof_main_pool_threads.value();'
                if text.count(needle) != 1:
                    raise ValueError('Worker patch needs inspection; do not silently package a different source')
                text = text.replace(needle, '    // Honor an explicit pool size; spare-CPU reservation applies only to auto sizing.\n'
                                    '    return std::max(1U, std::min(worker_cfg.nof_main_pool_threads.value(), avail_cpus));')
                data = text.encode()
            payload[f'third_party/{name}/{relative}'] = data
            count += 1
        provenance += [f'## {name}', '', f'Base revision: `{revision}`', f'Packaged source files: {count}',
                       '', 'Tracked working-tree changes before packaging:', '```text', status or '(none)', '```', '']
        if name == 'srsRAN_Project':
            provenance += ['Worker-count patch applied to the packaged copy only; local upstream tree was not modified.',
                           'Existing E2/KPM working-tree changes are preserved; see docs/existing-source.patch.',
                           'Do not apply docs/explicit-worker-count.patch again to this packaged copy.', '']
    payload['SOURCE_PROVENANCE.md'] = ('\n'.join(provenance) + '\n').encode()
    sums = ''.join(hashlib.sha256(data).hexdigest() + '  ' + name + '\n' for name, data in sorted(payload.items()))
    payload['SOURCE_SHA256SUMS.txt'] = sums.encode()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix('.zip.tmp')
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(payload.items()):
            archive.writestr('ai-ran-performance/' + name, data)
    with zipfile.ZipFile(temporary) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert not any('/results/' in n or '/build/' in n or '/.git/' in n or '/bin/' in n for n in names)
        assert all(n.endswith('.md') for n in names if n.startswith(('ai-ran-performance/reports/', 'ai-ran-performance/deliverables/')))
        for name, data in payload.items():
            assert archive.read('ai-ran-performance/' + name) == data
    temporary.replace(args.out)
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    args.out.with_suffix('.zip.sha256').write_text(digest + '  ' + args.out.name + '\n')
    print(f'{args.out}: {len(payload)} files; {args.out.stat().st_size:,} bytes; SHA256 {digest}')


if __name__ == '__main__':
    main()
