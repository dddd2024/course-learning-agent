import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { getMe } from '../api/auth'

const TOKEN_KEY = 'token'
const USERNAME_KEY = 'username'
const REMEMBER_KEY = 'auth_remember'

/**
 * Read the initial token at store creation.
 *
 * Redo Task A: when the user did NOT choose "记住登录" we must NOT fall
 * back to localStorage — a stale localStorage token was bypassing the
 * login page. We also proactively clear any leftover localStorage token
 * so the bad state cannot reappear.
 */
function readInitialToken(): string {
  const remembered = localStorage.getItem(REMEMBER_KEY) === '1'
  if (remembered) {
    return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY) || ''
  }
  // Not remembered: a leftover localStorage token is invalid — purge it.
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USERNAME_KEY)
  return sessionStorage.getItem(TOKEN_KEY) || ''
}

function readInitialUsername(): string {
  const remembered = localStorage.getItem(REMEMBER_KEY) === '1'
  if (remembered) {
    return localStorage.getItem(USERNAME_KEY) || sessionStorage.getItem(USERNAME_KEY) || ''
  }
  return sessionStorage.getItem(USERNAME_KEY) || ''
}

export const useAuthStore = defineStore('auth', () => {
  const remember = ref<boolean>(localStorage.getItem(REMEMBER_KEY) === '1')

  const token = ref<string>(readInitialToken())
  const username = ref<string>(readInitialUsername())

  // Redo Task A: authReady gates the router guard. Until ensureAuthReady
  // resolves we don't know whether the token is valid, so the guard must
  // wait (await) rather than trust token.value alone.
  const authReady = ref<boolean>(false)

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
    authReady.value = true
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
    authReady.value = true
  }

  /**
   * Ensure the auth state has been validated against the backend.
   *
   * Redo Task A: the router guard awaits this before deciding to allow a
   * protected route. If there is no token we mark authReady and return
   * false (guard redirects to /login). If a token exists we call
   * /auth/me; on 401 we clear it and return false.
   *
   * Idempotent: once authReady is true the stored token verdict is
   * reused until setToken/clearToken reset it.
   */
  async function ensureAuthReady(): Promise<boolean> {
    if (authReady.value) return !!token.value
    if (!token.value) {
      authReady.value = true
      return false
    }
    try {
      const { data } = await getMe()
      if (data.username) username.value = data.username
      authReady.value = true
      return true
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status
      if (status === 401) {
        clearToken()
        return false
      }
      // A timeout or temporary outage does not prove the session is invalid.
      // Keep the token so the current page can show a recoverable network error
      // instead of unexpectedly throwing the user back to the login screen.
      authReady.value = true
      return true
    }
  }

  return { token, username, isLoggedIn, remember, authReady, setToken, clearToken, ensureAuthReady }
})
