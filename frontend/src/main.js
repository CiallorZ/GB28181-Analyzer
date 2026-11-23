import { createApp } from 'vue'
import { createPinia } from 'pinia'
import AppIcon from './components/AppIcon.vue'
import App from './App.vue'
import router from './router'
import './styles/theme.css'

const app = createApp(App)
app.component('AppIcon', AppIcon)
app.use(createPinia())
app.use(router)
app.mount('#app')
