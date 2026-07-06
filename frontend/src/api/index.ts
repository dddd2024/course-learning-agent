import axios from 'axios'
import router from '../router'
import { useAuthStore } from '../stores/auth'

const request = axios.create({
  baseURL: 'http://localhost:8000/api/v1',
  timeout: 15000,
})

request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
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
