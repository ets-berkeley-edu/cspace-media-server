import {describe, expect, it} from 'vitest'
import {FAR_PAST_TIMES, kindWord, middlePath, timesOver, timesText} from '@/words'

describe('how the app names kinds and paths', () => {
  it('names a kind by its word, and "file" when the kind is not known (D151)', () => {
    expect(['image', 'card', 'pdf', '3D', 'audio', 'video'].map(kindWord))
      .toEqual(['image', 'catalog card', 'PDF', '3D model', 'audio file', 'video'])
    expect(kindWord(null)).toBe('file')
    expect(kindWord('')).toBe('file')
  })

  it('shortens a path in the middle, keeping the museum, both ends of the CSID and the size (D152)', () => {
    // Synthetic CSIDs only.
    expect(middlePath('/pahma/imageserver/blobs/0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b/derivatives/Medium/content'))
      .toBe('/pahma/imageserver/blobs/0f1e2d3c…3f4a5b/derivatives/Medium/content')
    expect(middlePath('/pahma/imageserver/blobs/59a733dd-d641/content')).toBe('/pahma/imageserver/blobs/59a733dd-d641/content')
    expect(middlePath('/x/' + 'a'.repeat(100))).toHaveLength(69)
  })
})

describe('how far past the delta threshold (issue #120)', () => {
  const check = (delta: number | null, previous: number | null = 500) =>
    ({previous_rows: previous, delta_percent: delta, threshold_percent: 5})

  it('says how many times the threshold a check is, only past it', () => {
    expect(timesOver(check(19))).toBeCloseTo(3.8)
    expect(timesOver(check(5))).toBe(0)
    expect(timesOver(check(2))).toBe(0)
    expect(timesOver(check(null, null))).toBe(0) // a first ETL list update: nothing to compare with
    expect(timesOver(check(50, 0))).toBe(0)
  })

  it('reads with one decimal, and from 100 times as a whole number', () => {
    expect(timesText(3.8)).toBe('3.8')
    expect(timesText(10)).toBe('10.0')
    expect(timesText(5751.352)).toBe('5,751')
  })

  it('is far past from 10 times, fixed', () => {
    expect(FAR_PAST_TIMES).toBe(10)
  })
})
