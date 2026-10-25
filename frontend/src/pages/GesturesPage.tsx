import { useCallback, useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import type { Gesture, RecordingSummary, Status, TrainResult } from '../types'

export function GesturesPage() {
  const [status, setStatus] = useState<Status | null>(null)
  const [gestures, setGestures] = useState<Gesture[]>([])
  const [recordings, setRecordings] = useState<RecordingSummary[]>([])
  const [selected, setSelected] = useState<string>('')
  const [name, setName] = useState('')
  const [rename, setRename] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [train, setTrain] = useState<TrainResult | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async (gestureId = selected) => {
    try {
      const [nextStatus, nextGestures, nextRecordings] = await Promise.all([
        api.status(),
        api.gestures(),
        api.recordings(gestureId || undefined),
      ])
      setStatus(nextStatus)
      setGestures(nextGestures.gestures)
      setRecordings(nextRecordings.recordings)
      setOffline(false)
      setError(null)
    } catch (err) {
      setOffline(true)
      setError(err instanceof Error ? err.message : 'Backend offline')
    }
  }, [selected])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!status?.active_recording) return
    const id = window.setInterval(() => void load(), 400)
    return () => window.clearInterval(id)
  }, [status?.active_recording, load])

  const current = gestures.find((gesture) => gesture.id === selected) ?? null
  const recording = status?.active_recording?.gesture_id === selected ? status.active_recording : null

  async function run(action: () => Promise<void>) {
    setBusy(true)
    try {
      await action()
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Request failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="stack">
      <div className="page-head">
        <div>
          <h1>Gestures</h1>
          <p>Create a gesture, record simulated examples, then train DTW.</p>
        </div>
        <div className="pill"><span className={`dot ${offline ? 'off' : 'on'}`} />{offline ? 'Backend offline' : 'Simulator active'}</div>
      </div>
      {error && <div className="banner">{error}</div>}
      <div className="grid-2">
        <div className="card">
          <h2>Library</h2>
          <form className="row" onSubmit={(event) => {
            event.preventDefault()
            void run(async () => {
              const created = await api.createGesture(name)
              setName('')
              setSelected(created.id)
              setRename(created.name)
            })
          }}>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="New gesture" aria-label="New gesture name" />
            <button className="primary" type="submit" disabled={busy || !name.trim()}>Create</button>
          </form>
          <div className="list" style={{ marginTop: 12 }}>
            {gestures.map((gesture) => (
              <div key={gesture.id} className={gesture.id === selected ? 'item selected' : 'item'}>
                <button className="linkish" type="button" onClick={() => { setSelected(gesture.id); setRename(gesture.name) }}>
                  <strong>{gesture.name}</strong>
                  <div className="meta">{gesture.recording_count ?? 0} {(gesture.recording_count ?? 0) === 1 ? 'example' : 'examples'}{status?.trained.includes(gesture.name) ? ' · trained' : ''}</div>
                </button>
              </div>
            ))}
            {gestures.length === 0 && <p className="note">No gestures yet.</p>}
          </div>
        </div>
        <div className="card stack">
          <h2>{current ? current.name : 'Select a gesture'}</h2>
          {current && (
            <>
              <form className="row" onSubmit={(event) => {
                event.preventDefault()
                void run(async () => {
                  const updated = await api.renameGesture(current.id, rename)
                  setRename(updated.name)
                })
              }}>
                <input value={rename} onChange={(event) => setRename(event.target.value)} aria-label="Rename gesture" />
                <button className="ghost" type="submit" disabled={busy}>Rename</button>
                <button className="danger" type="button" disabled={busy} onClick={() => {
                  if (window.confirm(`Delete ${current.name} and its recordings?`)) {
                    void run(async () => {
                      await api.deleteGesture(current.id)
                      setSelected('')
                    })
                  }
                }}>Delete</button>
              </form>
              <div className="row">
                <button className="primary" type="button" disabled={busy || Boolean(recording)} onClick={() => void run(async () => { await api.startRecording(current.id) })}>
                  Record example
                </button>
                <button className="ghost" type="button" disabled={!recording || recording.sample_count < 8} onClick={() => void run(async () => { await api.stopRecording() })}>
                  Stop and save
                </button>
                <button className="ghost" type="button" disabled={!recording} onClick={() => void run(async () => { await api.cancelRecording() })}>
                  Cancel
                </button>
              </div>
              <p className="note">
                {recording
                  ? `Recording simulated samples · ${recording.sample_count} captured. Source: ${recording.source}.`
                  : 'Recordings use the live synthetic feed and are stored with source synthetic. A physical glove is not connected.'}
              </p>
              <div className="list">
                {recordings.map((item) => (
                  <div key={item.id} className="item">
                    <div>
                      <strong>{item.sample_count} samples</strong>
                      <div className="meta">{item.duration_ms.toFixed(0)} ms · {item.created_at}</div>
                    </div>
                    <div className="row">
                      <span className="tag">{item.source === 'synthetic' ? 'SIMULATED' : item.source}</span>
                      <button className="danger" type="button" onClick={() => {
                        if (window.confirm('Delete this recording?')) {
                          void run(async () => { await api.deleteRecording(item.id) })
                        }
                      }}>Delete</button>
                    </div>
                  </div>
                ))}
                {recordings.length === 0 && <p className="note">No saved examples for this gesture.</p>}
              </div>
            </>
          )}
          <div>
            <button className="primary" type="button" disabled={busy || offline} onClick={() => void run(async () => setTrain(await api.train()))}>
              Train
            </button>
            <p className="note">
              {`Trained classes: ${status?.trained.length ? status.trained.join(', ') : 'none'}.${train ? ' Thresholds are DTW distances, not probabilities.' : ''}`}
            </p>
            {train && (
              <div className="list">
                {train.trained_classes.map((label) => (
                  <div key={label} className="item">
                    <strong>{label}</strong>
                    <span className="meta">threshold {train.thresholds[label]?.toFixed(3)} distance</span>
                  </div>
                ))}
                {train.trained_classes.length === 0 && <p className="note">Training needs at least two examples of a gesture.</p>}
              </div>
            )}
          </div>
          <div>
            <h2>Assign action</h2>
            <p className="note">
              The backend does not store or run actions. A recognized gesture is not wired to a key, app, or shell command.
            </p>
            <button className="ghost" type="button" disabled>Assign action</button>
          </div>
        </div>
      </div>
    </section>
  )
}
