import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './assets/main.css'

// ECharts registration lives in BaseChart.vue so the (large) charting library
// only loads on routes that actually render a chart — the home page doesn't.

createApp(App).use(createPinia()).use(router).mount('#app')
