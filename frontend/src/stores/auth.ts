import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string>(localStorage.getItem('token') || '')
  const username = ref<string>(localStorage.getItem('username') || '')

  const isLoggedIn = computed(() => !!token.value)

  function setToken(newToken: string, name?: string) {
    token.value = newToken
    localStorage.setItem('token', newToken)
    if (name) {
      username.value = name
      localStorage.setItem('username', name)
    }
  }

  function clearToken() {
    token.value = ''
    username.value = ''
    localStorage.removeItem('token')
    localStorage.removeItem('username')
  }

  return { token, username, isLoggedIn, setToken, clearToken }
})
