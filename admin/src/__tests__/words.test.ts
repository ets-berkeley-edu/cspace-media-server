import {describe, expect, it} from 'vitest'
import {FAR_PAST_TIMES, kindPlural, kindWord, middlePath, refusalWhy, stateSince, timesOver, timesText} from '@/words'

describe('how the app names kinds and paths', () => {
  it('names a kind by its word, and "file" when the kind is not known (D151)', () => {
    expect(['image', 'card', 'pdf', '3D', 'audio', 'video'].map(kindWord))
      .toEqual(['image', 'catalog card', 'PDF', '3D model', 'audio file', 'video'])
    expect(kindWord(null)).toBe('file')
    expect(kindWord('')).toBe('file')
  })

  it('names a kind in the plural, and "files" when the kind is not known', () => {
    expect(['image', 'card', 'pdf', '3D', 'audio', 'video'].map(kindPlural))
      .toEqual(['images', 'catalog cards', 'PDFs', '3D models', 'audio files', 'videos'])
    expect(kindPlural(null)).toBe('files')
    expect(kindPlural('hologram')).toBe('files')
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

describe('how far an update has got (November 5, 2026)', () => {
  const now = new Date('2026-11-06T07:36:00Z')
  const applying = {state: 'updating', updated_at: '2026-11-06T07:24:18Z'}

  it('says the rows applied and in all, once the worker has sent them', () => {
    expect(stateSince({...applying, progress: {done: 120000, total: 969351}}, now).text)
      .toBe('Applying since 07:24 UTC (12 min): 120,000 of 969,351 rows applied.')
  })

  it('says what is usual until then, and while checking', () => {
    expect(stateSince(applying, now).text).toBe('Applying since 07:24 UTC (12 min): usually a few minutes.')
    expect(stateSince({...applying, state: 'checking', progress: {done: 1, total: 2}}, now).text)
      .toBe('Checking since 07:24 UTC (12 min): usually a few minutes.')
  })
})

describe('why Media look up\'s verdict refuses (issue #208)', () => {
  const reasons = ['kind_not_served', 'restricted', 'original_not_served', 'no_derivatives_for_kind',
    'watermark_not_built', 'derivative_not_served']

  it('has a sentence for each reason without a verdict of its own, never just "not served"', () => {
    for (const reason of reasons) {
      const why = refusalWhy(reason, 'image', 'public', 'Medium')
      expect(why, reason).toBeTruthy()
      expect(why!.toLowerCase(), reason).not.toBe('not served')
      expect(why, reason).toContain('unavailable image')
    }
  })

  it('names audio and video in the plural, once', () => {
    expect(refusalWhy('kind_not_served', 'audio', 'public', null))
      .toBe('Serena doesn\'t serve audio files yet: a request gets the unavailable image.')
    expect(refusalWhy('kind_not_served', 'video', 'public', null))
      .toBe('Serena doesn\'t serve videos yet: a request gets the unavailable image.')
    expect(refusalWhy('kind_not_served', 'hologram', 'public', null)).toContain('(hologram)')
    expect(refusalWhy('kind_not_served', 'hologram', 'public', null)).not.toContain('yet')
  })

  it('says why from the access, the kind and the size', () => {
    expect(refusalWhy('restricted', 'pdf', 'restricted', null))
      .toBe('Its access is restricted, and the museum doesn\'t allow signed links for PDFs: a request gets the '
        + 'unavailable image.')
    expect(refusalWhy('restricted', 'image', 'private', null)).toContain('Its access is private, not public')
    expect(refusalWhy('watermark_not_built', 'image', 'public', 'FullHD')).toContain('watermarks the FullHD size')
    expect(refusalWhy('watermark_not_built', 'image', 'public', null)).toContain('watermarks these sizes')
    expect(refusalWhy('no_derivatives_for_kind', '3D', 'public', 'Medium')).toContain('A 3D model is served only')
  })

  it('has none for a reason with a verdict of its own', () => {
    expect(refusalWhy('recalled', 'image', 'public', null)).toBeNull()
    expect(refusalWhy('media_deleted', 'image', 'public', null)).toBeNull()
  })
})
