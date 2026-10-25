"""Check live USB/BLE motion packets without starting calibration."""
import argparse
import json
from pathlib import Path
import threading
import time

from motion_core import PacketReader, Orientation, scaled


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--transport', choices=('usb', 'ble'), default='usb')
    parser.add_argument('--port', default='COM5')
    parser.add_argument('--seconds', type=float, default=8)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 2 <= args.seconds <= 60:
        parser.error('--seconds must be 2..60')
    if args.transport == 'ble':
        from motion_ble import BleStream
        connection = BleStream(threading.Event())
        identity = connection.info.serial_number
        address = connection.info.device
        mtu = connection.mtu
    else:
        import serial
        connection = serial.Serial(port=None, baudrate=115200, timeout=0.1)
        connection.dtr = False
        connection.rts = False
        connection.port = args.port
        connection.open()
        connection.dtr = True
        connection.rts = True
        connection.reset_input_buffer()
        identity, address, mtu = None, args.port, None
    reader, orientation = PacketReader(), Orientation()
    packets = []
    began = time.monotonic()
    try:
        while time.monotonic() - began < args.seconds:
            data = connection.read(max(1, min(4096, connection.in_waiting)))
            for packet in reader.feed(data):
                packets.append(packet)
                for row in packet.samples:
                    orientation.update(scaled(row))
    finally:
        connection.close()
    gaps = sum(b.first_sample != (a.first_sample + a.count) & 0xFFFFFFFF or
               b.sequence != (a.sequence + 1) & 0xFFFFFFFF or
               b.fifo_resets != a.fifo_resets or b.i2c_errors != a.i2c_errors
               for a, b in zip(packets, packets[1:]))
    report = {'transport': args.transport, 'address': address, 'usb_identity': identity,
              'mtu': mtu, 'packets': len(packets), 'samples': sum(p.count for p in packets),
              'packet_errors': reader.errors, 'gaps': gaps, 'calibration_started': False}
    if len(packets) > 1:
        a, b = packets[0], packets[-1]
        report.update(sample_hz=(b.first_sample + b.count - a.first_sample - a.count) * 1e6 / (b.time_us - a.time_us),
                      ready=b.ready, fifo_resets_start=a.fifo_resets, fifo_resets_end=b.fifo_resets,
                      i2c_errors=b.i2c_errors, ble_dropped_frames=b.reserved,
                      temperature_c=b.temperature_c, last_angles_uncalibrated=orientation.angles(),
                      left_down=bool(b.contacts & 1), right_down=bool(b.contacts & 2),
                      left_presses=b.left_presses, right_presses=b.right_presses)
    report['passed'] = bool(report.get('ready') and report.get('sample_hz', 0) > 950 and
                            report['samples'] > 1000 and not gaps and not reader.errors)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
