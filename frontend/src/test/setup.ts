import '@testing-library/jest-dom'
import { vi } from 'vitest'

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    prefetch: vi.fn(),
  }),
  usePathname: vi.fn(() => ''),
  useSearchParams: () => new URLSearchParams(),
}))

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(), // Deprecated
    removeListener: vi.fn(), // Deprecated
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Polyfill localStorage for Node 22+ where globalThis.localStorage is undefined by default
const store = new Map<string, string>()
const mockLocalStorage = {
  getItem: vi.fn((k: string) => store.get(k) ?? null),
  setItem: vi.fn((k: string, v: string) => { store.set(k, String(v)) }),
  removeItem: vi.fn((k: string) => { store.delete(k) }),
  clear: vi.fn(() => { store.clear() }),
  key: vi.fn((i: number) => Array.from(store.keys())[i] ?? null),
  get length() { return store.size },
}
Object.defineProperty(window, 'localStorage', { value: mockLocalStorage, writable: true, configurable: true })
Object.defineProperty(globalThis, 'localStorage', { value: mockLocalStorage, writable: true, configurable: true })

// Mock @/lib/hooks/use-translation with standard t() function
vi.mock('../lib/hooks/use-translation', () => {
  return {
    useTranslation: () => ({
      t: (key: string) => key,
      language: 'en-US',
      setLanguage: vi.fn(),
    }),
  }
})

// Mock @/lib/hooks/use-auth
vi.mock('@/lib/hooks/use-auth', () => ({
  useAuth: vi.fn(() => ({
    user: { id: '1', email: 'test@example.com' },
    logout: vi.fn(),
    isLoading: false,
  })),
}))

// Mock @/lib/stores/sidebar-store
vi.mock('@/lib/stores/sidebar-store', () => ({
  useSidebarStore: vi.fn(() => ({
    isCollapsed: false,
    toggleCollapse: vi.fn(),
  })),
}))

// Mock @/lib/hooks/use-create-dialogs
vi.mock('@/lib/hooks/use-create-dialogs', () => ({
  useCreateDialogs: vi.fn(() => ({
    openSourceDialog: vi.fn(),
    openNotebookDialog: vi.fn(),
    openPodcastDialog: vi.fn(),
  })),
}))
