import { describe, expect, it } from 'vitest'
import { normalizeApiAssetUrl } from './assetUrl'

describe('normalizeApiAssetUrl', () => {
  it('removes the API prefix already supplied by the Axios client', () => {
    expect(normalizeApiAssetUrl('/api/v1/materials/images/329/file'))
      .toBe('/materials/images/329/file')
  })

  it('preserves already relative and external URLs', () => {
    expect(normalizeApiAssetUrl('/materials/page-assets/958/file'))
      .toBe('/materials/page-assets/958/file')
    expect(normalizeApiAssetUrl('https://example.test/image.png'))
      .toBe('https://example.test/image.png')
  })
})
