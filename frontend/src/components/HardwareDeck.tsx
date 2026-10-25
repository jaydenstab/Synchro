import { GloveMetrics } from './GloveMetrics'
import { PointerControl } from './PointerControl'
import { SpeechPanel } from './SpeechPanel'

export function HardwareDeck() {
  return (
    <div className="deck">
      <GloveMetrics />
      <div className="deck-split">
        <PointerControl />
        <SpeechPanel />
      </div>
    </div>
  )
}
