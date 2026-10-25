import { useEffect, useState } from 'react'
import { api } from '../api'
import type { AssistantStatus, CameraBridge, Status } from '../types'

export function SettingsPage() {
  const [status, setStatus] = useState<Status | null>(null)
  const [bridge, setBridge] = useState<CameraBridge | null>(null)
  const [assistant, setAssistant] = useState<AssistantStatus | null>(null)
  const [offline, setOffline] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    try {
      const [nextStatus, nextBridge, nextAssistant] = await Promise.all([
        api.status(),
        api.cameraBridge(),
        api.assistantStatus(),
      ])
      setStatus(nextStatus)
      setBridge(nextBridge)
      setAssistant(nextAssistant)
      setOffline(false)
      setError(null)
    } catch (err) {
      setOffline(true)
      setError(err instanceof Error ? err.message : 'Backend offline')
    }
  }

  useEffect(() => {
    void refresh()
  }, [])

  return (
    <section className="stack">
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Connection and input source.</p>
        </div>
        <button className="ghost" type="button" onClick={() => void refresh()}>Reconnect</button>
      </div>
      {error && <div className="banner">{error}</div>}
      <div className="card stack">
        <h2>Backend</h2>
        <div className="pill"><span className={`dot ${offline ? 'off' : 'on'}`} />{offline ? 'Offline' : 'Connected'}</div>
        <p className="note">{status?.source ?? 'Waiting for /api/status'}</p>
        <p className="note">Persistence: {status?.persistence ?? '—'}. Recordings stored: {status?.recordings ?? '—'}.</p>
      </div>
      <div className="card stack">
        <h2>Input source</h2>
        <p className="note">Simulator active. The live feed is synthetic. A physical glove adapter is not connected, so hardware cannot be selected.</p>
      </div>
      <div className="card stack">
        <h2>Camera</h2>
        <p className="note">{bridge?.available ? 'Bridge available' : 'Camera bridge unavailable'} · {bridge?.transport}</p>
        <p className="note">{bridge?.reason}</p>
      </div>
      <div className="card stack">
        <h2>Visual assistant</h2>
        <p className="note">
          {assistant
            ? assistant.configured
              ? `Gemini key is set on the server. Vision model ${assistant.vision_model}. Speech model ${assistant.stt_model}.`
              : 'GEMINI_API_KEY is not set. Add it to the backend environment and restart. The key is not sent to this page.'
            : 'Checking the visual assistant.'}
        </p>
        <p className="note">{assistant?.note ?? 'Uploads are discarded after each request.'}</p>
      </div>
      <details className="fold">
        <summary>Diagnostics</summary>
        <p className="note">Trained classes: {status?.trained.length ? status.trained.join(', ') : 'none'}.</p>
        <p className="note">Active recording: {status?.active_recording ? status.active_recording.label : 'none'}.</p>
      </details>
    </section>
  )
}
