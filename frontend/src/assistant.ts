export const MIN_RECORDING_MS = 400
export const MAX_RECORDING_MS = 60_000

const RECORDER_CANDIDATES = [
  'audio/webm;codecs=opus',
  'audio/webm',
  'audio/mp4',
  'audio/ogg;codecs=opus',
  'audio/ogg',
]

export function formatElapsed(ms: number): string {
  const safe = Number.isFinite(ms) ? Math.max(0, ms) : 0
  const total = Math.floor(safe / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${seconds.toString().padStart(2, '0')}`
}

export function recordingTooShort(durationMs: number): boolean {
  return !Number.isFinite(durationMs) || durationMs < MIN_RECORDING_MS
}

export function canSubmitQuestion(input: { hasImage: boolean; question: string; busy: boolean }): boolean {
  return input.hasImage && input.question.trim().length > 0 && !input.busy
}

export function captureEnabled(
  bridge: { available: boolean; connected: boolean } | null,
  busy: boolean,
): boolean {
  return Boolean(bridge?.available && bridge.connected) && !busy
}

export function preferredAudioMime(isTypeSupported: (value: string) => boolean): string {
  return RECORDER_CANDIDATES.find((candidate) => isTypeSupported(candidate)) ?? ''
}

export function micPermissionMessage(errorName: string): string {
  switch (errorName) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
    case 'SecurityError':
      return 'Microphone permission denied. Allow the microphone for this site, then try again.'
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return 'No microphone was found on this Mac.'
    case 'NotReadableError':
    case 'TrackStartError':
      return 'The microphone is busy in another app.'
    case 'TypeError':
      return 'This browser has no microphone API.'
    default:
      return 'The microphone could not start.'
  }
}

export function audioFilename(mimeType: string): string {
  const base = mimeType.split(';', 1)[0].trim().toLowerCase()
  if (base === 'audio/mp4' || base === 'audio/m4a' || base === 'audio/aac') return 'question.m4a'
  if (base === 'audio/ogg') return 'question.ogg'
  if (base === 'audio/wav' || base === 'audio/wave') return 'question.wav'
  return 'question.webm'
}
