"""Build a source-only review ZIP with an explicit inclusion policy."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from publication_files import content_issues, public_files

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    files = public_files(ROOT)
    manifest = {}
    prepared = []
    for path in sorted(set(files)):
        data = path.read_bytes()
        issues = content_issues(path, data)
        if issues:
            raise ValueError(f'unsafe release input {path.relative_to(ROOT)}: {issues}')
        if path.suffix in {'.py', '.sh', '.md', '.toml', '.json'}:
            data = data.replace(b'\r\n', b'\n')
        prepared.append((path.relative_to(ROOT).as_posix(), data))
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED) as bundle:
        for relative, data in prepared:
            bundle.writestr(relative, data)
            manifest[relative] = hashlib.sha256(data).hexdigest()
        bundle.writestr('SOURCE_MANIFEST.json', json.dumps(manifest, indent=2))
    print(json.dumps({'files': len(manifest), 'archive': str(output),
                      'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    build(parser.parse_args().output)
