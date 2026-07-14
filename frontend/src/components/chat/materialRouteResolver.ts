import { getChunk, listMaterials } from '../../api/material'

/**
 * Resolve a chunk to the stable public identity used by the learning route.
 *
 * Chat retrieval items intentionally stay compact. When an item was not a
 * formal citation it may not carry material_public_id, so resolve the chunk's
 * authoritative material_id and then map it through the owned course list.
 */
export async function resolveMaterialPublicId(
  courseId: number,
  chunkId: number,
  knownPublicId?: string | null,
): Promise<string> {
  if (knownPublicId) return knownPublicId

  const { data: chunk } = await getChunk(chunkId)
  const { data: materials } = await listMaterials(courseId, { page_size: 100 })
  const material = materials.items.find((item) => item.id === chunk.material_id)
  if (!material?.public_id) {
    throw new Error(`Unable to resolve material public id for chunk ${chunkId}`)
  }
  return material.public_id
}
