"""15-second stationary gyro calibration through the running camera viewer.

Run without --start to check readiness. --start requires the user to already
have put the MPU on a stable surface. It never opens a competing COM port.
"""
import argparse
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from motion_sensor import CONTROL_FILE


def call_control(endpoint, method='GET'):
    config = json.loads(CONTROL_FILE.read_text(encoding='utf-8'))
    port = config['port']
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('Invalid local control port')
    request = Request(f'http://127.0.0.1:{port}/{endpoint}', method=method,
                      headers={'X-Synchro-Token': config['token']})
    try:
        with urlopen(request, timeout=3) as response:
            return json.load(response)
    except HTTPError as error:
        raise ValueError(json.load(error).get('error', str(error))) from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', action='store_true', help='Start only when the MPU is stationary')
    args = parser.parse_args()
    try:
        status = call_control('status')
        if not args.start:
            print(json.dumps(status, indent=2))
            print('Readiness check only: calibration has NOT started.')
            print('READY' if status['ready'] and status['fresh'] else 'NOT READY: waiting for live MPU data.')
            return 0
        run_id = call_control('calibrate', 'POST')['id']
        print('Keep the MPU completely still for 15 seconds. No need to hold it level.', flush=True)
        deadline = time.monotonic() + 25
        last_second = -1
        while time.monotonic() < deadline:
            state = call_control('status')['calibration']
            if state.get('id') != run_id:
                raise ValueError('Calibration session changed; no success assumed')
            if state['state'] in ('passed', 'failed'):
                print(json.dumps(state, indent=2), flush=True)
                return 0 if state['state'] == 'passed' else 1
            second = int(15 * state.get('progress', 0))
            if second != last_second:
                print(f'{second}/15 seconds collected', flush=True)
                last_second = second
            time.sleep(0.2)
        raise ValueError('Timed out waiting for calibration; check the viewer before retrying')
    except (OSError, ValueError, KeyError, URLError) as error:
        print(f'Calibration tool: {error}. Open the updated camera viewer and connect the Nano.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
