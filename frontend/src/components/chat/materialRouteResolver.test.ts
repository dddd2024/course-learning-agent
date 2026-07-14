import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../api/material', () => ({
  getChunk: vi.fn(),
  listMaterials: vi.fn(),
}))

import { getChunk, listMaterials } from '../../api/material'
import { resolveMaterialPublicId } from './materialRouteResolver'

describe('resolveMaterialPublicId', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses a public id already carried by a formal citation', async () => {
    await expect(resolveMaterialPublicId(4, 9, 'public-9')).resolves.toBe('public-9')
    expect(getChunk).not.toHaveBeenCalled()
    expect(listMaterials).not.toHaveBeenCalled()
  })

  it('resolves an uncited retrieval chunk through owned material metadata', async () => {
    vi.mocked(getChunk).mockResolvedValue({ data: { material_id: 12 } } as any)
    vi.mocked(listMaterials).mockResolvedValue({
      data: {
        items: [
          { id: 11, public_id: 'public-11' },
          { id: 12, public_id: 'public-12' },
        ],
        total: 2,
      },
    } as any)

    await expect(resolveMaterialPublicId(4, 9)).resolves.toBe('public-12')
    expect(getChunk).toHaveBeenCalledWith(9)
    expect(listMaterials).toHaveBeenCalledWith(4, { page_size: 100 })
  })

  it('fails closed instead of opening the default material', async () => {
    vi.mocked(getChunk).mockResolvedValue({ data: { material_id: 99 } } as any)
    vi.mocked(listMaterials).mockResolvedValue({
      data: { items: [], total: 0 },
    } as any)

    await expect(resolveMaterialPublicId(4, 9)).rejects.toThrow(
      'Unable to resolve material public id',
    )
  })
})
