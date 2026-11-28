import { createApp } from 'vue'
import ScriptPanel from './ScriptPanel.vue'
import UserPanel from './UserPanel.vue'
import MaaEndPlanTable from './MaaEndPlanTable.vue'
import './panel.css'

const panels = { script: ScriptPanel, user: UserPanel, plan: MaaEndPlanTable }
createApp(panels[document.body.dataset.page as keyof typeof panels]).mount('#app')
