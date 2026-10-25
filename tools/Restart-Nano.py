"""Finish a Nano ESP32 DFU upload by sending the interface's DETACH request.

Some bundled dfu-util versions leave the sketch running after download and
--detach alone does not send a DFU-mode DETACH. Only targets Arduino 2341:0070.
Requires pyusb + libusb-package; never resets another USB device.
"""
import argparse
import usb.core
import usb.util
import libusb_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True, help='Exact Nano USB serial to restart')
    args = parser.parse_args()
    backend = libusb_package.get_libusb1_backend()
    devices = list(usb.core.find(find_all=True, idVendor=0x2341, idProduct=0x0070, backend=backend))
    matches = [device for device in devices if device.serial_number.upper() == args.serial.upper()]
    if len(matches) != 1:
        raise SystemExit('Expected exactly one matching Nano; no reset sent.')
    device = matches[0]
    interfaces = [i for i in device.get_active_configuration()
                  if i.bInterfaceClass == 0xFE and i.bInterfaceSubClass == 1]
    if len(interfaces) != 1:
        raise SystemExit('Expected exactly one DFU interface; no reset sent.')
    interface = interfaces[0].bInterfaceNumber
    try:
        usb.util.claim_interface(device, interface)
        device.ctrl_transfer(0x21, 0, 1000, interface, b'', timeout=1500)
        print('Sent Nano DFU restart request.')
    finally:
        usb.util.dispose_resources(device)


if __name__ == '__main__':
    main()
