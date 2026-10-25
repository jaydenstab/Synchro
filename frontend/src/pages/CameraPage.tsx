import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { GloveMetrics } from '../components/GloveMetrics'
import {
  MAX_RECORDING_MS,
  audioFilename,
  canSubmitQuestion,
  captureEnabled,
  formatElapsed,
  micPermissionMessage,
  preferredAudioMime,
  recordingTooShort,
} from '../assistant'
import type { CameraBridge, VisionAnswer } from '../types'

type ImageChoice = {
  blob: Blob
  name: string
  url: string
  source: 'upload' | 'camera'
}

type Busy = 'ask' | 'transcribe' | 'capture' | null

export function CameraPage() {
  const fileRef = useRef<HTMLInputElement>(null)
  const previewRef = useRef<string | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const recordingRef = useRef(false)
  const sessionRef = useRef(0)
  const startedAtRef = useRef(0)
  const timerRef = useRef<number | null>(null)

  const [bridge, setBridge] = useState<CameraBridge | null>(null)
  const [offline, setOffline] = useState(false)
  const [message, setMessage] = useState('Checking the local camera bridge.')
  const [image, setImage] = useState<ImageChoice | null>(null)
  const [resolution, setResolution] = useState('—')
  const [rotated, setRotated] = useState(false)
  const [question, setQuestion] = useState('')
  const [recording, setRecording] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [busy, setBusy] = useState<Busy>(null)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<VisionAnswer | null>(null)
  const [speaking, setSpeaking] = useState(false)
  const [configured, setConfigured] = useState<boolean | null>(null)

  function remember(blob: Blob, source: ImageChoice['source'], name: string) {
    const url = URL.createObjectURL(blob)
    if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    previewRef.current = url
    setImage({ blob, source, name, url })
    setResolution('—')
    setResult(null)
  }

  async function refresh() {
    try {
      const [next, assistant] = await Promise.all([api.cameraBridge(), api.assistantStatus()])
      setBridge(next)
      setConfigured(assistant.configured)
      setOffline(false)
      setMessage(next.reason)
    } catch (err) {
      setBridge(null)
      setConfigured(null)
      setOffline(true)
      setMessage(err instanceof Error ? err.message : 'Backend offline')
    }
  }

  useEffect(() => {
    void refresh()
    return () => {
      sessionRef.current += 1
      window.speechSynthesis?.cancel()
      if (timerRef.current !== null) window.clearInterval(timerRef.current)
      streamRef.current?.getTracks().forEach((track) => track.stop())
      if (previewRef.current) URL.revokeObjectURL(previewRef.current)
    }
  }, [])

  function stopClock() {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current)
      timerRef.current = null
    }
  }

  function releaseMicrophone() {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    recorderRef.current = null
    recordingRef.current = false
    setRecording(false)
    stopClock()
  }

  async function beginRecording() {
    if (recordingRef.current || busy) return
    const session = sessionRef.current + 1
    sessionRef.current = session
    setError(null)
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('This browser has no microphone API.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (session !== sessionRef.current) {
        stream.getTracks().forEach((track) => track.stop())
        return
      }
      const mime = preferredAudioMime((value) => MediaRecorder.isTypeSupported(value))
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
      chunksRef.current = []
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data)
      }
      recorder.onstop = () => {
        const duration = performance.now() - startedAtRef.current
        const type = recorder.mimeType || mime || 'audio/webm'
        const blob = new Blob(chunksRef.current, { type })
        chunksRef.current = []
        releaseMicrophone()
        if (recordingTooShort(duration)) {
          setError('Hold the microphone button a little longer, then release.')
          return
        }
        void sendAudio(blob, type)
      }
      streamRef.current = stream
      recorderRef.current = recorder
      recordingRef.current = true
      startedAtRef.current = performance.now()
      setElapsed(0)
      setRecording(true)
      timerRef.current = window.setInterval(() => {
        const next = performance.now() - startedAtRef.current
        setElapsed(next)
        if (next >= MAX_RECORDING_MS) {
          stopClock()
          if (recorder.state !== 'inactive') recorder.stop()
        }
      }, 200)
      recorder.start()
    } catch (err) {
      releaseMicrophone()
      const name = err instanceof DOMException ? err.name : 'Error'
      setError(micPermissionMessage(name))
    }
  }

  function finishRecording() {
    const recorder = recorderRef.current
    if (!recordingRef.current || !recorder || recorder.state === 'inactive') {
      sessionRef.current += 1
      return
    }
    recorder.stop()
  }

  async function sendAudio(blob: Blob, mimeType: string) {
    setBusy('transcribe')
    try {
      const transcript = await api.transcribe(blob, audioFilename(mimeType))
      setQuestion(transcript.transcript)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Transcription failed.')
    } finally {
      setBusy(null)
    }
  }

  function onFile(event: { target: HTMLInputElement }) {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    remember(file, 'upload', file.name || 'upload.jpg')
    setError(null)
  }

  async function capture() {
    setBusy('capture')
    setError(null)
    try {
      const blob = await api.captureFrame()
      remember(blob, 'camera', 'camera.jpg')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Camera bridge unavailable.')
    } finally {
      setBusy(null)
    }
  }

  function saveImage() {
    if (!image) return
    const link = document.createElement('a')
    link.href = image.url
    link.download = image.name || 'synchro-frame.jpg'
    link.click()
  }

  function stopSpeaking() {
    window.speechSynthesis?.cancel()
    setSpeaking(false)
  }

  async function ask() {
    if (!image || !canSubmitQuestion({ hasImage: true, question, busy: busy !== null || recording })) return
    setBusy('ask')
    setError(null)
    stopSpeaking()
    try {
      const answer = await api.askImage(image.blob, image.name, question.trim(), image.source)
      setResult(answer)
    } catch (err) {
      setResult(null)
      setError(err instanceof Error ? err.message : 'The request failed.')
    } finally {
      setBusy(null)
    }
  }

  function readAloud() {
    const text = result?.state === 'answered' ? result.answer : ''
    if (!text) return
    if (!window.speechSynthesis) {
      setError('This browser cannot read the answer aloud.')
      return
    }
    stopSpeaking()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.onend = () => setSpeaking(false)
    utterance.onerror = () => setSpeaking(false)
    setSpeaking(true)
    window.speechSynthesis.speak(utterance)
  }

  const connected = Boolean(bridge?.available && bridge.connected)
  const tone = offline ? 'off' : connected ? 'on' : 'warn'
  const bridgeLabel = offline ? 'Backend offline' : connected ? 'Viewer live' : bridge?.available ? 'Viewer idle' : 'Bridge unavailable'
  const working = busy !== null || recording
  const canAsk = canSubmitQuestion({ hasImage: Boolean(image), question, busy: working })
  const canCapture = captureEnabled(bridge, busy !== null)
  const sourceLabel = image?.source === 'camera'
    ? 'Native viewer JPEG. Not a simulated frame.'
    : image?.source === 'upload'
      ? 'Uploaded image. Not a simulated frame.'
      : 'No image yet. Nothing on this page is a simulated camera frame.'

  return (
    <section className="camera-page">
      <div className="page-head">
        <div>
          <h1>Camera</h1>
          <p>Ask about an uploaded photo, or capture a JPEG when the native viewer is live.</p>
        </div>
        <div className="pill">
          <span className={`dot ${tone}`} />
          {bridgeLabel}
        </div>
      </div>
      {error && <div className="banner" role="alert">{error}</div>}
      <div className="stage" aria-label="Camera preview">
        {image ? (
          <img
            className={rotated ? 'preview flipped' : 'preview'}
            src={image.url}
            alt={image.source === 'camera' ? 'JPEG from the native camera viewer' : 'Uploaded image'}
            onLoad={(event) => {
              const picture = event.currentTarget
              setResolution(`${picture.naturalWidth} × ${picture.naturalHeight}`)
            }}
          />
        ) : (
          <div>
            <h2>No camera image</h2>
            <p>{message}</p>
          </div>
        )}
      </div>
      <p className="note">{sourceLabel}</p>
      <GloveMetrics />
      <div className="toolbar">
        <div className="group">
          <button className="ghost" type="button" onClick={() => void refresh()}>Refresh</button>
          <button className="ghost" type="button" onClick={() => fileRef.current?.click()} disabled={busy !== null}>
            Upload Image
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            onChange={onFile}
          />
          <button
            className="ghost"
            type="button"
            disabled={!canCapture}
            title={canCapture ? 'Request a JPEG from the native viewer' : 'Camera bridge unavailable'}
            onClick={() => void capture()}
          >
            Capture Photo
          </button>
        </div>
        <div className="group">
          <label className="check">
            <input type="checkbox" checked={rotated} onChange={(event) => setRotated(event.target.checked)} />
            Rotate 180°
          </label>
          <button className="ghost" type="button" disabled={!image} onClick={saveImage}>Save Image</button>
        </div>
      </div>
      <div className="assistant">
        <div className="card stack">
          <h2>Question</h2>
          <div className="group">
            <button
              className={recording ? 'mic live' : 'ghost'}
              type="button"
              aria-pressed={recording}
              disabled={busy === 'ask' || busy === 'transcribe' || busy === 'capture'}
              onPointerDown={(event) => {
                if (event.button !== 0) return
                event.preventDefault()
                event.currentTarget.setPointerCapture(event.pointerId)
                void beginRecording()
              }}
              onPointerUp={(event) => {
                event.preventDefault()
                finishRecording()
              }}
              onPointerCancel={() => finishRecording()}
              onKeyDown={(event) => {
                if (event.repeat) return
                if (event.key === ' ' || event.key === 'Enter') {
                  event.preventDefault()
                  void beginRecording()
                }
              }}
              onKeyUp={(event) => {
                if (event.key === ' ' || event.key === 'Enter') {
                  event.preventDefault()
                  finishRecording()
                }
              }}
            >
              Hold to talk
            </button>
            {recording && (
              <span className="pill" role="status">
                <span className="dot off" />
                Recording {formatElapsed(elapsed)}
              </span>
            )}
            {busy === 'transcribe' && <span className="note">Transcribing…</span>}
          </div>
          <textarea
            className="question"
            value={question}
            placeholder="Type a question, or hold the microphone and edit the transcript."
            maxLength={2000}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <div className="group">
            <button className="primary" type="button" disabled={!canAsk} onClick={() => void ask()}>
              {busy === 'ask' ? 'Asking…' : 'Ask AI'}
            </button>
            {configured === false && (
              <span className="note">GEMINI_API_KEY is not set on the server.</span>
            )}
          </div>
          <p className="note">
            Releasing the microphone transcribes the clip. Ask AI sends the question. Nothing is sent before that.
          </p>
        </div>
        <div className="card stack">
          <h2>Answer</h2>
          <div className="answer" aria-live="polite">
            {busy === 'ask' && <p className="note">Asking Gemini…</p>}
            {result?.state === 'answered' && <p>{result.answer}</p>}
            {result?.state === 'unclear_image' && <p>{result.message}</p>}
            {!result && busy !== 'ask' && <p className="note">The answer appears here. Synchro does not run commands from it.</p>}
          </div>
          {result && (
            <p className="note">
              {result.model} · {result.declared_source === 'camera' ? 'native viewer JPEG' : 'uploaded image'} · not retained on the server
            </p>
          )}
          <div className="group">
            <button className="ghost" type="button" disabled={result?.state !== 'answered' || !result.answer} onClick={readAloud}>
              Read Answer Aloud
            </button>
            <button className="ghost" type="button" disabled={!speaking} onClick={stopSpeaking}>
              Stop Speaking
            </button>
          </div>
        </div>
      </div>
      <details className="fold">
        <summary>Diagnostics</summary>
        <div className="readouts">
          <div className="readout"><b>FPS</b><span>—</span></div>
          <div className="readout"><b>Resolution</b><span style={{ fontSize: 18 }}>{resolution}</span></div>
          <div className="readout"><b>Latency</b><span>—</span></div>
          <div className="readout"><b>Transport</b><span style={{ fontSize: 14 }}>{bridge?.transport ?? '—'}</span></div>
        </div>
        <p className="note">
          The native viewer in {bridge?.viewer ?? 'camera/synchro_mac'} owns the Bluetooth Classic session.
          FPS and latency stay blank here because this page does not receive the live frame clock.
          {bridge?.simulated === false ? ' Bridge status is not a simulated camera.' : ''}
        </p>
      </details>
    </section>
  )
}
