<template>
  <div class="app">
    <NavBar />
    <router-view v-slot="{ Component }">
      <keep-alive include="HomeView,ProjectView,LiveView,SearchView,SettingsView">
        <component :is="Component" />
      </keep-alive>
    </router-view>
    <AppToasts />
    <FirstLoginGuide />
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import NavBar from './components/NavBar.vue'
import AppToasts from './components/AppToasts.vue'
import FirstLoginGuide from './components/FirstLoginGuide.vue'
import { useAppStore } from './stores/app.js'

const store = useAppStore()

onMounted(async () => {
  await store.checkAuth()
  store.fetchAdminSettings().catch(() => {})
})
</script>
