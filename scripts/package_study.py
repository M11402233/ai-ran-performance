#!/usr/bin/env python3
"""One ZIP with evidence-backed acceptance, code and aggregate results."""
import argparse
from pathlib import Path
import shutil
import sys
import zipfile
ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('--out', type=Path, default=ROOT / 'deliverables/du-dqn-study.zip')
p.add_argument('--no-analysis', action='store_true', help='Package code while a live measurement is running; final remote cleanup uses default analysis.')
a = p.parse_args()
a.out.parent.mkdir(parents=True, exist_ok=True)
processed = ROOT / 'results/processed'
if not a.no_analysis:
    sys.path.insert(0, str(ROOT / 'analysis'))
    from build_outcome import build
    sessions = sorted(path for path in processed.glob('remote-session-*') if (path / 'status.json').exists())
    errors = []
    for session in sessions:
        try:
            build(session)
        except Exception as exc:
            errors.append(f'{session.name}: {type(exc).__name__}: {exc}')
            print(f'Acceptance analysis FAILED: {errors[-1]}', file=sys.stderr)
    if sessions:
        latest = sessions[-1]
        for name in ['completion.md', 'overview.png', 'caption.md', 'cache-overview.png', 'shared-split-comparison.csv', 'quality-summary.csv', 'all-runs.csv', 'perf-summary.csv', 'acceptance.csv']:
            source, target = latest / name, a.out.parent / name
            if source.exists():
                shutil.copyfile(source, target)
            elif target.exists():
                target.unlink()  # Never serve a previous session's figure as the current result.
        if errors:
            (a.out.parent / 'analysis-errors.md').write_text('# Acceptance analysis errors\n\n' + '\n'.join(errors) + '\n')
        elif (a.out.parent / 'analysis-errors.md').exists():
            (a.out.parent / 'analysis-errors.md').unlink()
files = [ROOT / 'README.md', ROOT / 'requirements-study.txt']
for directory in ['scripts', 'analysis', 'workloads', 'configs', 'tests', 'bin', 'docs']:
    files.extend(path for path in (ROOT / directory).rglob('*') if path.is_file() and '__pycache__' not in path.parts
                 and path.suffix in {'.py', '.sh', '.yml', '.md', '.txt', '.patch', ''})
for directory in processed.glob('*'):
    if directory.is_dir() and directory.name.startswith(('baseline-shared-', 'baseline-split-', 'matrix-', 'remote-session-')):
        files.extend(path for path in directory.rglob('*') if path.is_file() and path.suffix in {'.csv', '.png', '.md'})
latest_artifacts = [a.out.parent / name for name in ['completion.md', 'overview.png', 'caption.md', 'cache-overview.png', 'shared-split-comparison.csv', 'quality-summary.csv', 'all-runs.csv', 'perf-summary.csv', 'acceptance.csv', 'analysis-errors.md']]
# Build atomically; a download never observes a partially written ZIP.
temporary = a.out.with_suffix('.zip.tmp')
with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(set(files)):
        archive.write(path, Path('ai-ran-performance') / path.relative_to(ROOT))
    for path in latest_artifacts:
        if path.exists():
            archive.write(path, Path('ai-ran-performance') / path.name)
with zipfile.ZipFile(temporary) as archive:
    assert archive.testzip() is None
    assert not any(name.endswith(('.json', '.jsonl')) for name in archive.namelist())
    count = len(archive.namelist())
temporary.replace(a.out)
print(f'{a.out} ({count} files, {a.out.stat().st_size:,} bytes)')
