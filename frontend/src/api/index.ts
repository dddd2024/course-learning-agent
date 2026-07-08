import axios from 'axios'
import router from '../router'
import { useAuthStore } from '../stores/auth'

const request = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
  timeout: 15000,
})

request.interceptors.request.use(
  (config) => {
    // Security Task D: read token from the auth store (sessionStorage by
    // default, localStorage only when "记住登录" was chosen) instead of
    // always reading localStorage directly.
    const auth = useAuthStore()
    if (auth.token) {
      config.headers.Authorization = `Bearer ${auth.token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

request.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      const auth = useAuthStore()
      auth.clearToken()
      router.push('/login')
    }
    return Promise.reject(error)
  },
)

export default request
