import { vi } from 'vitest'
import { config } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ElementPlus from 'element-plus'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

// ---------------------------------------------------------------------------
// vue-router mock
// ---------------------------------------------------------------------------
// vi.hoisted ensures the mock objects exist before the vi.mock factory runs.
const { mockRoute, mockRouter } = vi.hoisted(() => {
  const route = {
    params: { id: '1' } as Record<string, string | undefined>,
    query: {} as Record<string, string | undefined>,
    path: '/',
    fullPath: '/',
  }
  const router = {
    push: vi.fn(),
    replace: vi.fn(),
    currentRoute: { value: route },
    beforeEach: vi.fn(),
    afterEach: vi.fn(),
    beforeResolve: vi.fn(),
  }
  return { mockRoute: route, mockRouter: router }
})

vi.mock('vue-router', () => ({
  useRouter: () => mockRouter,
  useRoute: () => mockRoute,
  onBeforeRouteLeave: vi.fn(),
  RouterLink: { template: '<a><slot /></a>' },
  RouterView: { template: '<div><slot /></div>' },
  createRouter: vi.fn(() => mockRouter),
  createWebHistory: vi.fn(),
}))

// ---------------------------------------------------------------------------
// vis-network mock (requires canvas, not available in jsdom)
// ---------------------------------------------------------------------------
vi.mock('vis-network/standalone', () => {
  class MockDataSet<T = any> {
    private items: T[] = []
    constructor(initial?: T[]) {
      if (initial) this.items = [...initial]
    }
    add(items: T | T[]) {
      if (Array.isArray(items)) this.items.push(...items)
      else this.items.push(items)
    }
    clear() {
      this.items = []
    }
    get() {
      return this.items
    }
    update() {
      /* no-op */
    }
    remove() {
      /* no-op */
    }
    length = 0
  }
  class MockNetwork {
    on() {
      /* no-op */
    }
    destroy() {
      /* no-op */
    }
    setOptions() {
      /* no-op */
    }
    stabilize() {
      /* no-op */
    }
    fit() {
      /* no-op */
    }
    redraw() {
      /* no-op */
    }
  }
  return { Network: MockNetwork, DataSet: MockDataSet }
})

// ---------------------------------------------------------------------------
// Element Plus global registration
// ---------------------------------------------------------------------------
if (!config.global.plugins.includes(ElementPlus)) {
  config.global.plugins.push(ElementPlus)
}

// Register Element Plus icons globally
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  if (!config.global.components[key]) {
    config.global.components[key] = component
  }
}

// ---------------------------------------------------------------------------
// jsdom environment globals
// ---------------------------------------------------------------------------
if (!window.matchMedia) {
  Object.defineProperty(window, 'matchMedia', {
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  })
}

if (!window.ResizeObserver) {
  class MockResizeObserver {
    observe = vi.fn()
    unobserve = vi.fn()
    disconnect = vi.fn()
  }
  Object.defineProperty(window, 'ResizeObserver', {
    value: MockResizeObserver,
    writable: true,
  })
}

if (!window.IntersectionObserver) {
  class MockIntersectionObserver {
    observe = vi.fn()
    unobserve = vi.fn()
    disconnect = vi.fn()
    takeRecords = vi.fn(() => [])
  }
  Object.defineProperty(window, 'IntersectionObserver', {
    value: MockIntersectionObserver,
    writable: true,
  })
}

if (!navigator.clipboard) {
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
}

// requestAnimationFrame polyfill for jsdom
if (!window.requestAnimationFrame) {
  window.requestAnimationFrame = vi.fn((cb: FrameRequestCallback) => {
    setTimeout(() => cb(Date.now()), 0)
    return 0
  })
  window.cancelAnimationFrame = vi.fn()
}

// ---------------------------------------------------------------------------
// Helper: create a testing pinia (lightweight alternative to @pinia/testing)
// ---------------------------------------------------------------------------
export function createTestingPinia() {
  const pinia = createPinia()
  setActivePinia(pinia)
  return pinia
}

// Ensure a default active pinia exists so stores don't throw at import time
setActivePinia(createPinia())

// ---------------------------------------------------------------------------
// Exports for test files
// ---------------------------------------------------------------------------
export { mockRoute, mockRouter }
