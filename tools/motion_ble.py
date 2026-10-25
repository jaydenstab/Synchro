"""BLE notification stream with the same framed packets as Nano USB CDC."""
import asyncio
import queue
import re
import threading
from types import SimpleNamespace

SERVICE_UUID = '8870a001-49a5-4a7c-8d92-a1f003b7d601'
DATA_UUID = '8870a002-49a5-4a7c-8d92-a1f003b7d601'
IDENTITY_UUID = '8870a003-49a5-4a7c-8d92-a1f003b7d601'
# A full SYNIMU1 notification is at most 238 bytes, which needs ATT payload room.
FULL_PACKET_MTU = 241


class BleStream:
    """Bounded blocking reader facade; all WinRT BLE calls live on one thread."""
    def __init__(self, stop_event, address=None, expected_identity=None):
        self.stopped = threading.Event()
        self.parent_stop = stop_event
        self.started = threading.Event()
        self.blocks = queue.Queue(maxsize=128)
        self.buffer = bytearray()
        self.error = None
        self.info = None
        self.address = address
        self.expected_identity = expected_identity
        self.thread = threading.Thread(target=self._thread_main, daemon=True)
        self.thread.start()
        while not self.started.wait(0.1):
            if stop_event.is_set():
                self.close()
                raise OSError('BLE connection cancelled')
        if self.error:
            self.close()
            raise OSError(self.error)

    def _thread_main(self):
        try:
            asyncio.run(self._connect())
        except Exception as error:
            self.error = f'Glove BLE: {error}'
        finally:
            self.started.set()
            self.stopped.set()

    async def _connect(self):
        from bleak import BleakClient, BleakScanner
        # A known address connects directly. Scanning inquires the same laptop
        # radio the camera is using for Classic video.
        if self.address:
            target, address = self.address, self.address
        else:
            devices = await BleakScanner.discover(timeout=4, service_uuids=[SERVICE_UUID])
            if len(devices) > 1:
                raise OSError('Multiple gloves found; choose one with --mpu-ble-address.')
            device = devices[0] if devices else None
            if device is None:
                raise OSError('Synchro-Glove not found. Power the Nano and enable laptop Bluetooth.')
            target, address = device, device.address
        if self.stopped.is_set() or self.parent_stop.is_set():
            return
        async with BleakClient(target, timeout=12, services=[SERVICE_UUID]) as client:
            identity = bytes(await client.read_gatt_char(IDENTITY_UUID)).decode('ascii')
            if not re.fullmatch(r'[0-9A-Fa-f]{12}', identity):
                raise OSError('Unexpected glove identity')
            if self.expected_identity and identity.upper() != self.expected_identity.upper():
                raise OSError('BLE glove is not the Nano previously connected over USB.')
            self.info = SimpleNamespace(device=address, serial_number=identity.upper())
            self.mtu = client.mtu_size

            def receive(characteristic, data):
                try:
                    self.blocks.put_nowait(bytes(data))
                except queue.Full:
                    self.error = 'Glove BLE reader fell behind; reconnecting to avoid stale angles.'
                    self.stopped.set()

            await client.start_notify(DATA_UUID, receive)
            self.started.set()
            while not self.stopped.is_set() and not self.parent_stop.is_set():
                if not client.is_connected:
                    raise OSError('Glove disconnected')
                await asyncio.sleep(0.05)
            if client.is_connected:
                await client.stop_notify(DATA_UUID)

    @property
    def in_waiting(self):
        return len(self.buffer)

    def read(self, count):
        if self.error:
            raise OSError(self.error)
        if not self.buffer:
            try:
                self.buffer.extend(self.blocks.get(timeout=0.1))
            except queue.Empty:
                if self.stopped.is_set():
                    raise OSError(self.error or 'Glove BLE disconnected')
                return b''
        # Drain one notification at a time; parser handles all fragmentation.
        result = bytes(self.buffer)
        self.buffer.clear()
        return result

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=2)
