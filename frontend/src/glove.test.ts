import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { contactPresentation, formatAngle } from './glove.ts'

describe('glove metric formatting', () => {
  it('formats signed degrees and a missing angle', () => {
    assert.equal(formatAngle(12.345), '+12.35°')
    assert.equal(formatAngle(-0.5), '-0.50°')
    assert.equal(formatAngle(0), '+0.00°')
    assert.equal(formatAngle(null), '—')
  })

  it('shows the Windows contact states', () => {
    const held = contactPresentation(true, true, 3, 3, 1000, 0)
    assert.equal(held.text, 'HELD')
    assert.equal(held.active, true)

    const tap = contactPresentation(true, false, 4, 3, 1000, 0)
    assert.equal(tap.text, 'TAP')
    assert.equal(tap.flashUntil, 1250)

    const released = contactPresentation(true, false, 4, 4, 1300, 1250)
    assert.equal(released.text, 'released')
    assert.equal(released.active, false)

    const dark = contactPresentation(false, null, 4, 4, 1300, 0)
    assert.equal(dark.text, 'NO SIGNAL')
    assert.equal(dark.active, false)
  })
})
