"""Package the Mac source demo and this camera's pairing PIN for local handoff."""
from pathlib import Path
import plistlib
import re
import zipfile


def main():
    project = Path(__file__).resolve().parents[1]
    source = project / 'tools' / 'mac-camera'
    names = ('SynchroCamera.swift', 'Info.plist', 'Start-Mac.command', 'README.md')
    contents = {name: (source / name).read_text(encoding='utf-8').encode('utf-8') for name in names}
    plist = plistlib.loads(contents['Info.plist'])
    assert plist['CFBundleExecutable'] == 'SynchroCamera'
    assert plist['NSBluetoothAlwaysUsageDescription']
    secret = (project / 'firmware' / 'SynchroCamBluetooth' / 'secrets.h').read_text(encoding='utf-8-sig')
    pin = re.search(r'^\s*#define\s+BT_PAIRING_PIN\s+"([0-9]{1,16})"', secret, re.MULTILINE)
    if not pin:
        raise RuntimeError('Camera pairing PIN was not found; no package created.')
    contents['PAIRING.txt'] = (
        'Camera: Synchro-Cam-BT\nBluetooth pairing PIN: ' + pin.group(1) + '\n'
        'For your nearby demo partner. Do not publish this package publicly.\n'
    ).encode('utf-8')
    destination = project / '.local' / 'partner' / 'Synchro-Camera-Mac.zip'
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            info = zipfile.ZipInfo('Synchro-Camera-Mac/' + name)
            info.create_system = 3
            info.external_attr = ((0o100755 if name.endswith('.command') else 0o100644) << 16)
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {'Synchro-Camera-Mac/' + name for name in contents}
        assert b'\r' not in archive.read('Synchro-Camera-Mac/Start-Mac.command')
    print(f'Created {destination} ({destination.stat().st_size:,} bytes; {len(contents)} files)')
    print('Mac source package only: compilation and Mac Bluetooth testing are pending.')


if __name__ == '__main__':
    main()
