export const ANGLE_CAPTIONS = ['ROLL / X', 'PITCH / Y', 'YAW / RELATIVE'] as const
export const CONTACT_CAPTIONS = ['Index / LEFT CLICK', 'Middle / RIGHT CLICK'] as const

export function formatAngle(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—'
  const text = Math.abs(value).toFixed(2)
  return `${value < 0 ? '-' : '+'}${text}°`
}

export function contactPresentation(
  fresh: boolean,
  down: boolean | null,
  presses: number,
  previous: number | null,
  now: number,
  flashUntil: number,
): { text: string; active: boolean; flashUntil: number } {
  let until = flashUntil
  if (previous != null && presses > previous) until = now + 250
  if (!fresh || down == null) {
    return { text: 'NO SIGNAL', active: false, flashUntil: until }
  }
  const tapping = now < until
  return {
    text: down ? 'HELD' : tapping ? 'TAP' : 'released',
    active: down || tapping,
    flashUntil: until,
  }
}
