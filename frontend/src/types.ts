export type Sample = {
  t_ms: number
  ax: number
  ay: number
  az: number
  gx: number
  gy: number
  gz: number
}

export type Gesture = {
  id: string
  name: string
  created_at: string
  updated_at: string
  recording_count?: number
}

export type RecordingSummary = {
  id: string
  gesture_id: string
  gesture_name?: string
  source: string
  sample_count: number
  duration_ms: number
  created_at: string
  session_id: string
}

export type ActiveRecording = {
  recording_id: string
  gesture_id: string
  label: string
  session_id: string
  source: string
  sample_count: number
  started_at: number
}

export type Status = {
  source: string
  trained: string[]
  recordings: number
  counts: Record<string, number>
  gestures: Gesture[]
  active_recording: ActiveRecording | null
  persistence: string
}

export type TrainResult = {
  trained_classes: string[]
  recordings: number
  thresholds: Record<string, number>
}

export type Prediction = {
  label: string
  closest_class: string
  distance: number
  threshold: number
  match: boolean
  distances: Record<string, number>
  note: string
}

export type MotionStatus = {
  connected: boolean
  ready: boolean
  fresh: boolean
  transport: string | null
  status: string
  line: string
  angles: [number, number, number] | null
  sample_hz: number
  temperature_c: number | null
  left_down: boolean | null
  right_down: boolean | null
  left_presses: number
  right_presses: number
  tracking_restarts: number
  calibrated: boolean
  calibration_state: string
  calibration_progress: number
  calibration_note: string
  calibrate_enabled: boolean
  simulated: boolean
  pointer?: PointerStatus
  speech?: SpeechStatus | null
}

export type PointerStatus = {
  enabled: boolean
  available: boolean
  message: string
  speed: number
  invert_x: boolean
  invert_y: boolean
  auto_enable: boolean
  stabilized: boolean
  sideways_axis: string
  left_clicks: number
  right_clicks: number
  manual_pause: boolean
}

export type SpeechStatus = {
  listening: boolean
  status: string
  model: string
  device: string | null
  level: number
  voice: boolean
  results: number
  dropped: number
  latency_ms: number | null
  error: string | null
  text: string
}

export type SpeechDevice = {
  id: number | null
  label: string
}

export type CameraBridge = {
  available: boolean
  connected: boolean
  capture_ready: boolean
  transport: string
  viewer: string
  reason: string
  width: number | null
  height: number | null
  frame: 'none' | 'native-viewer'
  simulated: boolean
}

export type AssistantStatus = {
  configured: boolean
  vision_model: string
  stt_model: string
  timeout_seconds: number
  max_image_bytes: number
  max_audio_bytes: number
  media_retained: boolean
  note: string
}

export type VisionAnswer = {
  state: 'answered' | 'unclear_image'
  answer: string
  message: string
  model: string
  declared_source: 'upload' | 'camera'
  media_retained: boolean
  simulated: boolean
}

export type Transcript = {
  state: 'transcribed'
  transcript: string
  model: string
  media_retained: boolean
}

export type TelemetryMessage = {
  kind: string
  source: string
  motion: string
  sample: Sample
}
