import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import App from './App.vue'
import router from './router'
import pinia from './stores'
import './styles/main.css'

const app = createApp(App)

for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.use(pinia)
app.use(router)
app.use(ElementPlus)

// Task A: replay any frontend error reports queued while the backend was
// unreachable during the previous session. Fire-and-forget on boot.
import('./utils/errorReport')
  .then(({ flushPendingErrorReports }) => flushPendingErrorReports())
  .catch(() => {
    // best-effort
  })

app.mount('#app')
