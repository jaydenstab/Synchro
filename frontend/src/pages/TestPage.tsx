import { useEffect, useRef, useState } from 'react'
import { api, telemetryUrl } from '../api'
import { Chart } from '../components/Chart'
import type { Prediction, Sample, TelemetryMessage } from '../types'

export function TestPage() {
  const [testing, setTesting] = useState(false)
  const [samples, setSamples] = useState<Sample[]>([])
  const [prediction, setPrediction] = useState<Prediction | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [offline, setOffline] = useState(false)
  const [simulatedMotion, setSimulatedMotion] = useState<string>('')
  const [source, setSource] = useState<string>('')
  const stageRef = useRef<HTMLDivElement>(null)
  const samplesRef = useRef<Sample[]>([])
  const testingRef = useRef(false)

  useEffect(() => {
    testingRef.current = testing
  }, [testing])

  useEffect(() => {
    if (!testing) return
    let socket: WebSocket | null = null
    let closed = false
    const connect = () => {
      socket = new WebSocket(telemetryUrl())
      socket.onopen = () => setOffline(false)
      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as TelemetryMessage
        if (message.kind !== 'sample' || !message.sample) return
        setSource(message.source)
        setSimulatedMotion(message.motion)
        const previous = samplesRef.current[samplesRef.current.length - 1]
        const restarted = previous != null && message.sample.t_ms <= previous.t_ms
        const next = restarted ? [message.sample] : [...samplesRef.current, message.sample].slice(-160)
        samplesRef.current = next
        setSamples(next)
      }
      socket.onerror = () => setOffline(true)
      socket.onclose = () => {
        if (!closed && testingRef.current) {
          setOffline(true)
          window.setTimeout(connect, 1000)
        }
      }
    }
    connect()
    const timer = window.setInterval(() => {
      const windowSamples = samplesRef.current.slice(-80)
      if (windowSamples.length < 8) return
      void api.predict(windowSamples).then((result) => {
        setPrediction(result)
        setError(null)
      }).catch((err: unknown) => {
        setPrediction(null)
        setError(err instanceof Error ? err.message : 'Prediction failed')
      })
    }, 900)
    return () => {
      closed = true
      window.clearInterval(timer)
      socket?.close()
    }
  }, [testing])

  const accepted = prediction?.match === true
  const label = prediction ? (prediction.match ? prediction.label : 'unknown') : '—'

  return (
    <section className="stack">
      <div className="page-head">
        <div>
          <h1>Test</h1>
          <p>Live recognition from the backend. Distance is not a confidence percentage.</p>
        </div>
        <div className="pill">
          <span className={`dot ${offline ? 'off' : testing ? 'on' : ''}`} />
          {offline ? 'Backend offline' : testing ? 'Testing' : 'Idle'}
        </div>
      </div>
      {error && <div className="banner">{error}</div>}
      <div className="split">
        <div className="card present" ref={stageRef}>
          <div className="meta">{source === 'synthetic' ? 'SIMULATED SENSOR DATA' : source || 'No telemetry yet'}</div>
          <h2 className={`hero-label ${prediction ? (accepted ? 'accepted' : 'rejected') : ''}`}>{label}</h2>
          <p className="note">
            {prediction
              ? (prediction.match ? 'Accepted' : 'Rejected') + ` · closest ${prediction.closest_class}`
              : 'Start testing to classify the live feed.'}
          </p>
          <p className="note">{prediction?.note}</p>
        </div>
        <div className="stack">
          <div className="readouts">
            <div className="readout"><b>DTW distance</b><span>{prediction ? prediction.distance.toFixed(3) : '—'}</span></div>
            <div className="readout"><b>Threshold</b><span>{prediction ? prediction.threshold.toFixed(3) : '—'}</span></div>
            <div className="readout"><b>Result</b><span style={{ fontSize: 18 }}>{prediction ? (prediction.match ? 'Accepted' : 'Rejected') : '—'}</span></div>
            <div className="readout"><b>Software action</b><span style={{ fontSize: 16 }}>None</span></div>
          </div>
          <p className="note">No action map exists, so recognition does not trigger a key, click, or app.</p>
          <div className="row">
            <button className="primary" type="button" onClick={() => {
              setTesting((value) => !value)
              if (testing) {
                samplesRef.current = []
                setSamples([])
              }
            }}>{testing ? 'Stop testing' : 'Start testing'}</button>
            <button className="ghost" type="button" onClick={() => {
              const node = stageRef.current
              if (!node) return
              if (document.fullscreenElement) void document.exitFullscreen()
              else void node.requestFullscreen()
            }}>Present</button>
          </div>
          {source === 'synthetic' && (
            <p className="note">Simulator pattern in this window: {simulatedMotion || '—'}. That label is the generator, not the recognizer.</p>
          )}
        </div>
      </div>
      <details className="fold">
        <summary>Accelerometer and gyroscope</summary>
        <div className="stack">
          <Chart samples={samples} axes={['ax', 'ay', 'az']} caption="Accelerometer m/s² · mint x, white y, gray z" />
          <Chart samples={samples} axes={['gx', 'gy', 'gz']} caption="Gyroscope rad/s · mint x, white y, gray z" />
        </div>
      </details>
    </section>
  )
}
