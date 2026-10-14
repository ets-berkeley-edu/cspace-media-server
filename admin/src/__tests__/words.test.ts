import {describe, expect, it} from 'vitest'
import {kindWord, middlePath} from '@/words'

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
