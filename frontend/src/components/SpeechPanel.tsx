import { useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import type { SpeechDevice, SpeechStatus } from '../types'

const EMPTY: SpeechStatus = {
  listening: false,
  status: 'Mic off · Parakeet v2 + Silero · local',
  model: 'parakeet-tdt-0.6b-v2',
  device: null,
  level: 0,
  voice: false,
  results: 0,
  dropped: 0,
  latency_ms: null,
  error: null,
  text: '',
}

export function SpeechPanel() {
  const [speech, setSpeech] = useState<SpeechStatus>(EMPTY)
  const [devices, setDevices] = useState<SpeechDevice[]>([{ id: null, label: 'Default laptop microphone' }])
  const [device, setDevice] = useState<number | null>(null)
  const [note, setNote] = useState(EMPTY.status)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let stopped = false
    void api.speechDevices().then((body) => {
      if (stopped) return
      setDevices(body.devices)
      if (body.error) setNote(body.error)
    }).catch(() => undefined)
    async function pull() {
      try {
        const next = await api.speech()
        if (stopped) return
        setSpeech(next)
        setNote(next.error || next.status)
      } catch (err) {
        if (!stopped) setNote(err instanceof ApiError ? err.message : 'Backend offline')
      }
    }
    void pull()
    const timer = window.setInterval(() => void pull(), 400)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [])

  async function toggle() {
    setBusy(true)
    try {
      const next = speech.listening ? await api.stopSpeech() : await api.startSpeech(device)
      setSpeech(next)
      setNote(next.error || next.status)
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : 'Microphone did not start')
    } finally {
      setBusy(false)
    }
  }

  async function clear() {
    try {
      const next = await api.clearSpeech()
      setSpeech(next)
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : 'Could not clear the transcript')
    }
  }

  const detail = speech.latency_ms != null
    ? `${note} · last decode ${(speech.latency_ms / 1000).toFixed(1)}s`
    : note

  return (
    <section className="card controls" aria-label="Local speech">
      <h2>Speech</h2>
      <div className="group">
        <button className={speech.listening ? 'danger' : 'primary'} type="button" disabled={busy} onClick={() => void toggle()}>
          {speech.listening ? 'Stop mic' : 'Start mic'}
        </button>
        <select
          value={device ?? ''}
          disabled={speech.listening}
          onChange={(event) => setDevice(event.target.value === '' ? null : Number(event.target.value))}
        >
          {devices.map((item) => (
            <option key={item.label} value={item.id ?? ''}>{item.label}</option>
          ))}
        </select>
        <button className="ghost" type="button" onClick={() => void clear()}>Clear text</button>
      </div>
      <div className="meter" aria-hidden="true">
        <span style={{ width: `${Math.round(Math.min(1, speech.level) * 100)}%` }} />
      </div>
      <p className="note">{speech.listening ? `MIC ON · ${detail}` : detail}</p>
      <pre className="transcript">{speech.text || 'Transcript appears here after a short pause.'}</pre>
    </section>
  )
}
