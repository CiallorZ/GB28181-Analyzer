import { panelChange } from './utils/panelChange'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import AppIcon from './components/AppIcon.vue'
import App from './App.vue'
import router from './router'
// Import order is deliberate: theme.css and goodui.css define structure and
// layout only; tokens.css comes last among the token/color files so its shared
// custom properties (--radius-*, --font-*, --dur-*, --app-header-height, etc.)
// are the deterministic single source of truth, including responsive overrides.
// desktop-workspace.css follows with higher-specificity component overrides.
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
