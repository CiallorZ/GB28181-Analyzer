import { panelChange } from './utils/panelChange'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import AppIcon from './components/AppIcon.vue'
import App from './App.vue'
import router from './router'
import './styles/theme.css'
import './styles/goodui.css'
import './styles/tokens.css'
import './styles/desktop-workspace.css'
import { initInterface } from './stores/interface'

initInterface()
const app = createApp(App)
app.directive('panel-change', panelChange)
app.component('AppIcon', AppIcon)
app.use(createPinia())
app.use(router)
app.mount('#app')
router.isReady().then(() => window.nsh?.postMessage?.('workspace-ready'))
