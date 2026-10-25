import os
import tempfile

os.environ['VISIONGLOVE_TELEMETRY_PERIOD'] = '0.001'
os.environ['VISIONGLOVE_DATA_DIR'] = tempfile.mkdtemp(prefix='visionglove-test-')
# Keep tests off the developer .env and off a viewer that happens to be open.
os.environ['GEMINI_API_KEY'] = ''
os.environ['SYNCHRO_CAMERA_BRIDGE_URL'] = 'http://127.0.0.1:9'
os.environ['VISIONGLOVE_MOTION_USB'] = '0'
os.environ['SYNCHRO_WINDOWS_CAMERA'] = '0'
