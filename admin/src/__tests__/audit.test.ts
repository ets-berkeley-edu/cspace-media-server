import {describe, expect, it} from 'vitest'
import {detailLines, targetOf} from '@/words'

describe('the audit log, readable', () => {
  it('shows details one field per line', () => {
    expect(detailLines({reason: 'Testing', rows: null, expires_at: 1791918889})).toEqual([
      {label: 'Reason', value: 'Testing'},
      {label: 'Expires at', value: '2026-10-13 19:14:49 UTC'}
    ])
    const sha = '88f538917c2' + '0'.repeat(53)
    expect(detailLines({file_name: 'servable-list.tsv', sha256: sha})).toEqual([
      {label: 'File name', value: 'servable-list.tsv'},
      {label: 'SHA-256', value: '88f538917c20…', full: sha}
    ])
    expect(detailLines({})).toEqual([])
    // An override's kind goes before its reason (issue #120); one made before has none.
    expect(detailLines({kind: 'first_load', reason: 'UCJEPS\'s first load', delta_percent: 99})).toEqual([
      {label: 'Reason', value: 'First load: UCJEPS\'s first load'}, {label: 'Delta percent', value: '99'}])
    expect(detailLines({reason: 'PAHMA republished many images'})).toEqual([
      {label: 'Reason', value: 'PAHMA republished many images'}])
  })

  it('shows an acknowledged alert by its kind, refresh date and subject', () => {
    expect(targetOf('alert_acknowledge', '2026-10-11#threshold_overridden#pahma-2026-10-11-2#1791746089'))
      .toBe('Threshold overridden · 2026-10-11 · pahma-2026-10-11-2')
    expect(targetOf('alert_acknowledge', '2026-10-11#missed_deadline#2026-10-11'))
      .toBe('Missed deadline · 2026-10-11')
    expect(targetOf('update_retry', 'pahma-2026-10-11-3')).toBe('pahma-2026-10-11-3')
  })
})
