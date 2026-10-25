"""Build a source handoff ZIP, excluding credentials, captures and local state."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = ('README.md', 'HANDOFF.md', 'requirements.txt', 'bluetooth-camera.example.json', '.gitignore')
SOURCE_DIRS = ('firmware', 'hardware', 'tools')
EXTENSIONS = {'.md', '.txt', '.json', '.py', '.ps1', '.ino', '.h', '.cjs', '.swift', '.command', '.plist', '.svg', '.png'}
EXCLUDED_PARTS = {'__pycache__', 'node_modules', '.venv', '.git', '.local', '.build', 'backups', '.DS_Store'}
SECRET_PATTERNS = (rb'gsk_[A-Za-z0-9]{25,}', rb'sk-(?:proj-)?[A-Za-z0-9_-]{35,}',
                   rb'AQ\.[A-Za-z0-9_-]{30,}', rb'AIza[A-Za-z0-9_-]{30,}',
                   rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')


def files_to_share():
    paths = [ROOT / name for name in TOP_FILES]
    for directory in SOURCE_DIRS:
        paths.extend(p for p in (ROOT / directory).rglob('*')
                     if p.is_file() and p.suffix.lower() in EXTENSIONS
                     and not any(part in EXCLUDED_PARTS for part in p.relative_to(ROOT).parts)
                     and p.name not in ('secrets.h', 'PAIRING.txt')
                     and not p.name.startswith('.env'))
    return sorted(paths, key=lambda p: p.relative_to(ROOT).as_posix())


def validate_payload(payload):
    # Check private firmware credentials by exact value without displaying them.
    private_values = []
    for header in ROOT.glob('firmware/*/secrets.h'):
        source = header.read_text(encoding='utf-8-sig')
        for pattern in (r'BT_PAIRING_PIN\s+"([^"]+)"', r'AP_PASSWORD\[\]\s*=\s*"([^"]+)"'):
            private_values.extend(re.findall(pattern, source))
    for name, data in payload.items():
        if name.endswith('.png'):
            continue
        if any(re.search(pattern, data) for pattern in SECRET_PATTERNS):
            raise ValueError(f'Credential-like content detected in {name}; package not created.')
        for value in private_values:
            if re.search(rb'(?<![\w])' + re.escape(value.encode()) + rb'(?![\w])', data):
                raise ValueError(f'Private firmware credential detected in {name}; package not created.')


def package(destination):
    paths = files_to_share()
    payload = {p.relative_to(ROOT).as_posix(): p.read_bytes() for p in paths}
    validate_payload(payload)
    contents = ('Complete shareable source project. Read README.md, then HANDOFF.md.\n\n'
                + '\n'.join(payload) + '\n\n'
                'Excluded: credentials/private secrets.h, .local runtime state and media,\n'
                '.build outputs, backups, .git, model caches, environments and bytecode.\n')
    payload['PACKAGE-CONTENTS.txt'] = contents.encode()
    payload['SHA256SUMS.txt'] = ''.join(
        f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name, data in sorted(payload.items())
    ).encode()
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids overwriting an earlier handoff.
    with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payload.items():
            info = zipfile.ZipInfo('Synchro-Project/' + name)
            info.create_system = 3
            info.external_attr = (0o100755 if name.endswith('.command') else 0o100644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {'Synchro-Project/' + n for n in payload}
        for name, data in payload.items():
            assert archive.read('Synchro-Project/' + name) == data
    report = {'zip': str(destination), 'files': len(payload), 'bytes': destination.stat().st_size,
              'sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
              'credential_scan': 'passed', 'archive_integrity': 'passed'}
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    package(parser.parse_args().output)
