import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getMe } from '../api/auth'

const TOKEN_KEY = 'token'
const USERNAME_KEY = 'username'
const REMEMBER_KEY = 'auth_remember'

export const useAuthStore = defineStore('auth', () => {
  // Security Task D: prefer sessionStorage so the token is cleared when
  // the browser closes (mitigates XSS token theft). Only use localStorage
  // when the user explicitly chose "记住登录" (remember me).
  const remember = ref<boolean>(localStorage.getItem(REMEMBER_KEY) === '1')

  function readStorage(key: string): string {
    if (remember.value) {
      return localStorage.getItem(key) || sessionStorage.getItem(key) || ''
    }
    return sessionStorage.getItem(key) || localStorage.getItem(key) || ''
  }

  const token = ref<string>(readStorage(TOKEN_KEY))
  const username = ref<string>(readStorage(USERNAME_KEY))

  const isLoggedIn = computed(() => !!token.value)

  function setToken(newToken: string, name?: string, rememberMe = false) {
    remember.value = rememberMe
    if (rememberMe) {
      localStorage.setItem(REMEMBER_KEY, '1')
    } else {
      localStorage.removeItem(REMEMBER_KEY)
    }
    token.value = newToken
    username.value = name || username.value
    // Always clear both stores first to avoid stale duplicates.
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(USERNAME_KEY)
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USERNAME_KEY)
    const store = rememberMe ? localStorage : sessionStorage
    store.setItem(TOKEN_KEY, newToken)
    if (username.value) {
      store.setItem(USERNAME_KEY, username.value)
    }
  }

  function clearToken() {
    token.value = ''
    username.value = ''
    remember.value = false
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(USERNAME_KEY)
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USERNAME_KEY)
    localStorage.removeItem(REMEMBER_KEY)
  }

  // Task B: validate the token against /auth/me on app boot. If the
  // backend rejects it (401) the axios interceptor clears the token and
  // the router guard redirects to /login. Returns true when the token
  // is still valid.
  async function validateToken(): Promise<boolean> {
    if (!token.value) return false
    try {
      const { data } = await getMe()
      // Keep the username in sync with the server-side truth.
      if (data.username) username.value = data.username
      return true
    } catch {
      clearToken()
      return false
    }
  }

  return { token, username, isLoggedIn, remember, setToken, clearToken, validateToken }
})
