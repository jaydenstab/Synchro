import { useEffect, useRef, useState } from 'react'
import { ApiError, api } from '../api'
import {
  ANGLE_CAPTIONS,
  CONTACT_CAPTIONS,
  contactPresentation,
  formatAngle,
} from '../glove'
import type { MotionStatus } from '../types'

const EMPTY: MotionStatus = {
  connected: false,
  ready: false,
  fresh: false,
  transport: null,
  status: 'Looking for Nano USB...',
  line: 'Looking for Nano USB...',
  angles: null,
  sample_hz: 0,
  temperature_c: null,
  left_down: null,
  right_down: null,
  left_presses: 0,
  right_presses: 0,
  tracking_restarts: 0,
  calibrated: false,
  calibration_state: 'idle',
  calibration_progress: 0,
  calibration_note: 'Not calibrated. Yaw can drift.',
  calibrate_enabled: false,
  simulated: false,
}

export function GloveMetrics() {
  const [motion, setMotion] = useState<MotionStatus>(EMPTY)
  const [note, setNote] = useState(EMPTY.calibration_note)
  const [busy, setBusy] = useState(false)
  const flashes = useRef<[number, number]>([0, 0])
  const presses = useRef<[number | null, number | null]>([null, null])
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let stopped = false
    async function pull() {
      try {
        const next = await api.motion()
        if (stopped) return
        setMotion(next)
        setNote(next.calibration_note)
      } catch (err) {
        if (stopped) return
        setMotion(EMPTY)
        setNote(err instanceof ApiError ? err.message : 'Backend offline')
      }
    }
    void pull()
    const timer = window.setInterval(() => {
      setTick((value) => value + 1)
      void pull()
    }, 300)
    return () => {
      stopped = true
      window.clearInterval(timer)
    }
  }, [])

  const now = Date.now()
  const contacts = [
    { down: motion.left_down, count: motion.left_presses },
    { down: motion.right_down, count: motion.right_presses },
  ].map((item, index) => {
    const view = contactPresentation(
      motion.fresh,
      item.down,
      item.count,
      presses.current[index],
      now,
      flashes.current[index],
    )
    flashes.current[index] = view.flashUntil
    presses.current[index] = item.count
    return { ...view, count: item.count }
  })
  void tick

  async function calibrate() {
    setBusy(true)
    try {
      const next = await api.calibrateMotion()
      setMotion(next)
      setNote(next.calibration_note)
    } catch (err) {
      setNote(err instanceof ApiError ? err.message : 'Calibration did not start')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="glove" aria-label="Glove metrics">
      <div className="angles">
        {ANGLE_CAPTIONS.map((caption, index) => (
          <div key={caption} className="angle">
            <b>{caption}</b>
            <span>{formatAngle(motion.angles?.[index])}</span>
          </div>
        ))}
      </div>
      <div className="contacts">
        {CONTACT_CAPTIONS.map((caption, index) => (
          <div key={caption} className={contacts[index].active ? 'contact live' : 'contact'}>
            {caption}: {contacts[index].text}  ·  {contacts[index].count} taps
          </div>
        ))}
      </div>
      <p className="line">{motion.line}</p>
      <div className="calibrate">
        <button
          className="ghost"
          type="button"
          disabled={!motion.calibrate_enabled || busy}
          onClick={() => void calibrate()}
        >
          Calibrate — hold still 15 s
        </button>
        <div className="meter" aria-hidden="true">
          <span style={{ width: `${Math.round(motion.calibration_progress * 100)}%` }} />
        </div>
      </div>
      <p className="note">{note}</p>
    </section>
  )
}
