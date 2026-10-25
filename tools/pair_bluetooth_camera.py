"""Pair only the camera identified over USB, using the Windows Bluetooth API.

Uses the device's generated PIN. Does not enable discovery on the laptop,
change security settings, remove devices, or pair unrelated nearby devices.
"""
import ctypes as ct
from ctypes import wintypes as wt
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


class SystemTime(ct.Structure):
    _fields_ = [(field, wt.WORD) for field in
                ('year', 'month', 'day_of_week', 'day', 'hour', 'minute', 'second', 'milliseconds')]


class Address(ct.Union):
    _fields_ = [('value', ct.c_ulonglong), ('bytes', ct.c_ubyte * 6)]


class Device(ct.Structure):
    _fields_ = [('size', wt.DWORD), ('address', Address), ('device_class', wt.ULONG),
                ('connected', wt.BOOL), ('remembered', wt.BOOL), ('authenticated', wt.BOOL),
                ('last_seen', SystemTime), ('last_used', SystemTime), ('name', wt.WCHAR * 248)]


class Search(ct.Structure):
    _fields_ = [('size', wt.DWORD), ('authenticated', wt.BOOL), ('remembered', wt.BOOL),
                ('unknown', wt.BOOL), ('connected', wt.BOOL), ('inquiry', wt.BOOL),
                ('timeout', ct.c_ubyte), ('radio', wt.HANDLE)]


def pair():
    config = json.loads((ROOT / '.local' / 'bluetooth-camera.json').read_text(encoding='utf-8-sig'))
    mac = config['bt_address']
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', mac):
        raise ValueError('Invalid camera address')
    target = int(mac.replace(':', ''), 16)
    secrets = (ROOT / 'firmware' / 'SynchroCamBluetooth' / 'secrets.h').read_text(encoding='utf-8-sig')
    match = re.search(r'#define BT_PAIRING_PIN "([0-9]{4,16})"', secrets)
    if not match:
        raise ValueError('Missing camera PIN')
    pin = match[1]
    api = ct.WinDLL('bthprops.cpl', use_last_error=True)
    api.BluetoothFindFirstDevice.argtypes = [ct.POINTER(Search), ct.POINTER(Device)]
    api.BluetoothFindFirstDevice.restype = wt.HANDLE
    api.BluetoothFindNextDevice.argtypes = [wt.HANDLE, ct.POINTER(Device)]
    api.BluetoothFindNextDevice.restype = wt.BOOL
    api.BluetoothFindDeviceClose.argtypes = [wt.HANDLE]
    api.BluetoothFindDeviceClose.restype = wt.BOOL
    api.BluetoothAuthenticateDevice.argtypes = [wt.HWND, wt.HANDLE, ct.POINTER(Device), wt.LPWSTR, wt.ULONG]
    api.BluetoothAuthenticateDevice.restype = wt.DWORD
    api.BluetoothGetDeviceInfo.argtypes = [wt.HANDLE, ct.POINTER(Device)]
    api.BluetoothGetDeviceInfo.restype = wt.DWORD
    search = Search(ct.sizeof(Search), True, True, True, True, True, 4, None)
    device = Device()
    device.size = ct.sizeof(Device)
    print(f'Searching for Synchro-Cam-BT at {mac}...', flush=True)
    handle = api.BluetoothFindFirstDevice(ct.byref(search), ct.byref(device))
    if not handle:
        raise ct.WinError(ct.get_last_error())
    found = None
    try:
        while True:
            if device.address.value == target:
                found = Device.from_buffer_copy(device)
                break
            device = Device()
            device.size = ct.sizeof(Device)
            if not api.BluetoothFindNextDevice(handle, ct.byref(device)):
                break
    finally:
        api.BluetoothFindDeviceClose(handle)
    if found is None:
        raise RuntimeError('Camera not discovered. Keep it powered nearby and retry.')
    if found.name != 'Synchro-Cam-BT':
        raise RuntimeError(f'Unexpected name for the camera address: {found.name}')
    if found.authenticated:
        print('Camera is already paired.', flush=True)
        return
    result = api.BluetoothAuthenticateDevice(None, None, ct.byref(found), pin, len(pin))
    if result not in (0, 259):
        raise ct.WinError(result)
    result = api.BluetoothGetDeviceInfo(None, ct.byref(found))
    if result:
        raise ct.WinError(result)
    if not found.authenticated:
        raise RuntimeError('Windows has not confirmed pairing.')
    print('PAIRING_OK: Synchro-Cam-BT authenticated with Windows.', flush=True)


if __name__ == '__main__':
    pair()
