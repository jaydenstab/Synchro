import { useEffect, useRef } from 'react'
import type { Sample } from '../types'

const COLORS = ['#3ddc97', '#f3f6f4', '#7f8c86']

export function Chart({ samples, axes, caption }: { samples: Sample[]; axes: Array<keyof Sample>; caption: string }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const context = canvas.getContext('2d')
    if (!context) return
    const width = canvas.clientWidth
    const height = canvas.clientHeight
    const ratio = window.devicePixelRatio || 1
    canvas.width = Math.floor(width * ratio)
    canvas.height = Math.floor(height * ratio)
    context.setTransform(ratio, 0, 0, ratio, 0, 0)
    context.clearRect(0, 0, width, height)
    context.fillStyle = '#000'
    context.fillRect(0, 0, width, height)
    if (samples.length < 2) return
    const series = axes.map((axis) => samples.map((sample) => Number(sample[axis])))
    const flat = series.flat()
    const min = Math.min(...flat)
    const max = Math.max(...flat)
    const span = max - min || 1
    series.forEach((values, index) => {
      context.beginPath()
      context.strokeStyle = COLORS[index % COLORS.length]
      context.lineWidth = 1.5
      values.forEach((value, point) => {
        const x = (point / (values.length - 1)) * width
        const y = height - ((value - min) / span) * (height - 16) - 8
        if (point === 0) context.moveTo(x, y)
        else context.lineTo(x, y)
      })
      context.stroke()
    })
  }, [samples, axes])

  return (
    <div>
      <div className="meta" style={{ marginBottom: 6 }}>{caption}</div>
      <canvas ref={ref} className="chart" />
    </div>
  )
}
