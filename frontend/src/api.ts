import type {
  AssistantStatus,
  CameraBridge,
  Gesture,
  Prediction,
  RecordingSummary,
  Sample,
  Status,
  TrainResult,
  MotionStatus,
  SpeechDevice,
  SpeechStatus,
  Transcript,
  VisionAnswer,
} from './types'

export class ApiError extends Error {
  status: number
  code: string

  constructor(status: number, message: string, code = '') {
    super(message)
    this.status = status
    this.code = code
  }
}

async function readBody<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = response.statusText || 'Request failed'
    let code = ''
    try {
      const body = await response.json() as { detail?: unknown; code?: string }
      if (typeof body.code === 'string') code = body.code
      if (typeof body.detail === 'string' && body.detail.trim()) message = body.detail
      else if (body.detail != null) message = JSON.stringify(body.detail)
    } catch {
      /* keep status text */
    }
    throw new ApiError(response.status, message, code)
  }
  return response.json() as Promise<T>
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    })
  } catch {
    throw new ApiError(0, 'Backend offline')
  }
  return readBody<T>(response)
}

async function upload<T>(path: string, form: FormData): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { method: 'POST', body: form })
  } catch {
    throw new ApiError(0, 'Backend offline')
  }
  return readBody<T>(response)
}

export function telemetryUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/telemetry`
}

export const api = {
  status: () => request<Status>('/api/status'),
  cameraBridge: () => request<CameraBridge>('/api/camera/bridge'),
  motion: () => request<MotionStatus>('/api/motion'),
  calibrateMotion: () => request<MotionStatus>('/api/motion/calibrate', { method: 'POST' }),
  updatePointer: (body: Record<string, unknown>) => request<MotionStatus>('/api/pointer', {
    method: 'POST',
    body: JSON.stringify(body),
  }),
  speech: () => request<SpeechStatus>('/api/speech'),
  speechDevices: () => request<{ devices: SpeechDevice[]; error: string | null }>('/api/speech/devices'),
  startSpeech: (device: number | null) => request<SpeechStatus>('/api/speech/start', {
    method: 'POST',
    body: JSON.stringify({ device }),
  }),
  stopSpeech: () => request<SpeechStatus>('/api/speech/stop', { method: 'POST' }),
  clearSpeech: () => request<SpeechStatus>('/api/speech/clear', { method: 'POST' }),
  gestures: () => request<{ gestures: Gesture[] }>('/api/gestures'),
  createGesture: (name: string) => request<Gesture>('/api/gestures', { method: 'POST', body: JSON.stringify({ name }) }),
  renameGesture: (id: string, name: string) => request<Gesture>(`/api/gestures/${id}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  deleteGesture: (id: string) => request<{ deleted: boolean }>(`/api/gestures/${id}`, { method: 'DELETE' }),
  recordings: (gestureId?: string) => {
    const query = gestureId ? `?gesture_id=${encodeURIComponent(gestureId)}` : ''
    return request<{ recordings: RecordingSummary[] }>(`/api/recordings${query}`)
  },
  deleteRecording: (id: string) => request<{ deleted: boolean }>(`/api/recordings/${id}`, { method: 'DELETE' }),
  startRecording: (gestureId: string) => request<Status['active_recording']>('/api/recordings/start', {
    method: 'POST',
    body: JSON.stringify({ gesture_id: gestureId, source: 'synthetic' }),
  }),
  stopRecording: () => request<RecordingSummary & { saved: boolean }>('/api/recordings/stop', { method: 'POST' }),
  cancelRecording: () => request<{ cancelled: boolean }>('/api/recordings/cancel', { method: 'POST' }),
  train: () => request<TrainResult>('/api/train', { method: 'POST' }),
  predict: (samples: Sample[]) => request<Prediction>('/api/predict', {
    method: 'POST',
    body: JSON.stringify({ samples }),
  }),
  assistantStatus: () => request<AssistantStatus>('/api/assistant/status'),
  askImage: (blob: Blob, filename: string, question: string, declaredSource: 'upload' | 'camera') => {
    const form = new FormData()
    form.append('image', blob, filename)
    form.append('question', question)
    form.append('declared_source', declaredSource)
    return upload<VisionAnswer>('/api/assistant/ask', form)
  },
  transcribe: (blob: Blob, filename: string) => {
    const form = new FormData()
    form.append('audio', blob, filename)
    return upload<Transcript>('/api/assistant/transcribe', form)
  },
  previewFrame: () => fetchJpeg('/api/camera/preview'),
  captureFrame: () => fetchJpeg('/api/camera/capture'),
}

async function fetchJpeg(path: string): Promise<Blob> {
  let response: Response
  try {
    response = await fetch(path, { cache: 'no-store' })
  } catch {
    throw new ApiError(0, 'Backend offline')
  }
  if (!response.ok) {
    await readBody<never>(response)
  }
  const type = response.headers.get('content-type') || ''
  if (!type.includes('image/jpeg')) {
    throw new ApiError(502, 'The camera bridge did not return a JPEG.', 'invalid_image')
  }
  return response.blob()
}
