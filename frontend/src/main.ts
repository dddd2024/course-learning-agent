import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import pinia from './stores'
import { useAuthStore } from './stores/auth'
import './styles/main.css'

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(pinia)
app.use(router)
app.use(ElementPlus)

// Redo Task A/C: replay pending frontend error reports ONLY after auth is
// validated. Flushing before login would hit 401 and (previously) drop the
// queue. The router guard triggers ensureAuthReady; we additionally flush
// here once auth resolves so reports land even on pages that don't guard.
const auth = useAuthStore()
// If auth already resolved (e.g. token absent), flush immediately or skip
// when unauthenticated (reports need a valid user).
auth.ensureAuthReady().then((ok) => {
  if (!ok) return // not logged in — keep the queue for next login
  import('./utils/errorReport')
    .then(({ flushPendingErrorReports }) => flushPendingErrorReports())
    .catch(() => {
      // best-effort
    })
}).catch(() => {
  // best-effort
})

app.mount('#app')
