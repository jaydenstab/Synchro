import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import {
  audioFilename,
  canSubmitQuestion,
  captureEnabled,
  formatElapsed,
  micPermissionMessage,
  preferredAudioMime,
  recordingTooShort,
} from './assistant.ts'

describe('camera assistant controls', () => {
  it('formats the recording timer', () => {
    assert.equal(formatElapsed(0), '0:00')
    assert.equal(formatElapsed(5400), '0:05')
    assert.equal(formatElapsed(62_000), '1:02')
    assert.equal(formatElapsed(Number.NaN), '0:00')
  })

  it('rejects a tap that is too short to be speech', () => {
    assert.equal(recordingTooShort(120), true)
    assert.equal(recordingTooShort(400), false)
  })

  it('does not submit a vision question until there is an image, text, and no in-flight request', () => {
    assert.equal(canSubmitQuestion({ hasImage: false, question: 'What is this?', busy: false }), false)
    assert.equal(canSubmitQuestion({ hasImage: true, question: '   ', busy: false }), false)
    assert.equal(canSubmitQuestion({ hasImage: true, question: 'What is this?', busy: true }), false)
    assert.equal(canSubmitQuestion({ hasImage: true, question: 'What is this?', busy: false }), true)
  })

  it('enables capture only when the native bridge is connected and the page is idle', () => {
    assert.equal(captureEnabled(null, false), false)
    assert.equal(captureEnabled({ available: false, connected: false }, false), false)
    assert.equal(captureEnabled({ available: true, connected: false }, false), false)
    assert.equal(captureEnabled({ available: true, connected: true }, true), false)
    assert.equal(captureEnabled({ available: true, connected: true }, false), true)
  })

  it('prefers a recorder mime the backend can send to Gemini', () => {
    assert.equal(preferredAudioMime((value) => value === 'audio/webm;codecs=opus'), 'audio/webm;codecs=opus')
    assert.equal(preferredAudioMime((value) => value === 'audio/mp4'), 'audio/mp4')
    assert.equal(preferredAudioMime(() => false), '')
    assert.equal(audioFilename('audio/mp4'), 'question.m4a')
    assert.equal(audioFilename('audio/webm;codecs=opus'), 'question.webm')
  })

  it('explains microphone permission denial without starting another recording', () => {
    assert.match(micPermissionMessage('NotAllowedError'), /permission denied/i)
    assert.match(micPermissionMessage('NotFoundError'), /no microphone/i)
    assert.match(micPermissionMessage('NotReadableError'), /busy/i)
    assert.match(micPermissionMessage('TypeError'), /no microphone API/i)
    assert.match(micPermissionMessage('AbortError'), /could not start/i)
  })
})
