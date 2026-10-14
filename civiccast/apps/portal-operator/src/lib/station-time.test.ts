import { describe, expect, it } from 'vitest'
import {
  dateToStationDateTimeLocal,
  effectiveStationTimeZone,
  nextStationWeeklyFireTimes,
  stationWallClockToDate,
} from './station-time'

describe('station wall-clock scheduling', () => {
  it('matches the backend UTC fallback for an unset or invalid station timezone', () => {
    expect(effectiveStationTimeZone('local')).toBe('UTC')
    expect(effectiveStationTimeZone('No/Such_Zone')).toBe('UTC')
  })

  it('resolves the selected wall time in the station zone, independent of the browser zone', () => {
    const instant = stationWallClockToDate('2026-07-04T19:00', 'America/Denver')
    expect(instant?.toISOString()).toBe('2026-07-05T01:00:00.000Z')
    expect(dateToStationDateTimeLocal(instant!, 'America/Denver')).toBe('2026-07-04T19:00')
  })

  it('rejects a nonexistent spring clock time', () => {
    expect(stationWallClockToDate('2026-03-08T02:30', 'America/Denver')).toBeNull()
  })

  it('chooses the earlier instant during a repeated fall clock hour', () => {
    expect(stationWallClockToDate('2026-11-01T01:30', 'America/Denver')?.toISOString())
      .toBe('2026-11-01T07:30:00.000Z')
  })

  it('skips a weekly spring-gap occurrence and continues at the same station wall time', () => {
    const fires = nextStationWeeklyFireTimes(
      [6], '02:30', 'America/Denver', 1, new Date('2026-03-07T12:00:00Z'),
    )
    expect(fires.map((fire) => fire.toISOString())).toEqual(['2026-03-15T08:30:00.000Z'])
  })
})
