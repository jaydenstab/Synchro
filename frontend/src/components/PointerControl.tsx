import { useEffect, useState } from 'react'
import { ApiError, api } from '../api'
import type { PointerStatus } from '../types'

const EMPTY: PointerStatus = {
  enabled: false,
  available: false,
  message: 'Pointer follows the glove after calibration.',
  speed: 1,
  invert_x: false,
  invert_y: false,
  auto_enable: true,
  stabilized: true,
  sideways_axis: 'X',
  left_clicks: 0,
  right_clicks: 0,
  manual_pause: false,
}

export function PointerControl() {
  const [pointer, setPointer] = useState<PointerStatus>(EMPTY)
  const [note, setNote] = useState(EMPTY.message)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let stopped = false
    async function pull() {
      try {
        const motion = await api.motion()
        if (stopped || !motion.pointer) return
        setPointer(motion.pointer)
        setNote(motion.pointer.message)
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

  async function send(body: Record<string, unknown>) {
    setBusy(true)
    try {
      const motion = await api.updatePointer(body)
      if (motion.pointer) {
        setPointer(motion.pointer)
        setNote(motion.pointer.message)
      }
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : 'Pointer did not update')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card controls" aria-label="Pointer">
      <h2>Pointer</h2>
      <p className="note">{note}</p>
      <div className="group">
        <button
          className="primary"
          type="button"
          disabled={busy}
          onClick={() => void send({ enabled: !pointer.enabled })}
        >
          {pointer.enabled ? 'Pause pointer' : 'Enable pointer'}
        </button>
        <button className="ghost" type="button" disabled={busy} onClick={() => void send({ recenter: true })}>
          Set neutral
        </button>
      </div>
      <div className="group">
        <label className="check">
          <input
            type="checkbox"
            checked={pointer.auto_enable}
            onChange={(event) => void send({ auto_enable: event.target.checked })}
          />
          Auto cursor
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={pointer.stabilized}
            onChange={(event) => void send({ stabilize: event.target.checked })}
          />
          Stabilize
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={pointer.invert_x}
            onChange={(event) => void send({ invert_x: event.target.checked })}
          />
          Reverse X
        </label>
        <label className="check">
          <input
            type="checkbox"
            checked={pointer.invert_y}
            onChange={(event) => void send({ invert_y: event.target.checked })}
          />
          Reverse Y
        </label>
      </div>
      <div className="group">
        <label className="check">
          Sideways axis
          <select
            value={pointer.sideways_axis}
            onChange={(event) => void send({ sideways_axis: event.target.value })}
          >
            <option value="X">X</option>
            <option value="Y">Y</option>
          </select>
        </label>
        <label className="check">
          Sensitivity {pointer.speed.toFixed(2)}×
          <input
            type="range"
            min={0.25}
            max={2}
            step={0.05}
            value={pointer.speed}
            onChange={(event) => void send({ speed: Number(event.target.value) })}
          />
        </label>
      </div>
      <p className="meta">
        Left clicks {pointer.left_clicks} · Right clicks {pointer.right_clicks}
        {pointer.available ? '' : ' · Cursor injection is available on Windows.'}
      </p>
    </section>
  )
}
