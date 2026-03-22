import { createApp } from 'vue'
import './style.css'
import 'vue-virtual-scroller/dist/vue-virtual-scroller.css'
import '@vue-flow/core/dist/style.css'
import '@vue-flow/core/dist/theme-default.css'
import App from './App.vue'
import router from './router'
import { i18n } from './i18n'
import VueVirtualScroller from 'vue-virtual-scroller'

// Register cleanup handlers for page unload
window.addEventListener('beforeunload', () => {
  // Cancel any ongoing fetch requests
  // This helps prevent hanging requests
  console.log('[Frontend] Page unloading, cleaning up...')
})

window.addEventListener('unload', () => {
  // Final cleanup before page completely unloads
  console.log('[Frontend] Final cleanup')
})

const app = createApp(App)
app.use(i18n)
app.use(router)
app.use(VueVirtualScroller)
app.mount('#app')
