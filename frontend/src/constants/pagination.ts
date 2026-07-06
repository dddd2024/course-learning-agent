/** 分页常量集中维护，禁止页面直接写死 magic number。 */

/** 默认每页条数，用于常规分页列表。 */
export const DEFAULT_PAGE_SIZE = 20

/** 最大每页条数，与后端 `le=100` 校验保持一致，用于下拉/全量加载场景。 */
export const MAX_PAGE_SIZE = 100
