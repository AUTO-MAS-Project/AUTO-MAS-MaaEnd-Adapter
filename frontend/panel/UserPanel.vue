<script setup lang="ts">
import { computed, onMounted, shallowRef, watch } from 'vue'
import { usePanel, type ConfigValue } from './bridge'
import ConfigField from './ConfigField.vue'
import InventoryFields from './InventoryFields.vue'
import SanityField from './SanityField.vue'
import { choices, rewardTasks, taskGroups, type ResourceOptions, type RouteGroup } from './options'

const panel = usePanel()
const { config, disabled, working, error, status, t } = panel
type Context = {
  path: string | null
  controller: string
  base: 'shared' | 'independent' | 'native'
  quickConfig: boolean
  sanityStrategy: 'MAS' | 'Native' | 'Inventory'
  sanityMode: string
  essenceMode: string
  plans: Record<string, { name: string; key: Record<string, ConfigValue> }>
  inventoryDefaults: Record<string, string>
}
const context = shallowRef<Context>()
const resources = shallowRef<ResourceOptions>()
let contextRevision = 0
const task = computed(() => config.value.Task ?? {})
const supported = computed(
  () =>
    !resources.value || resources.value.controllerTypes[context.value?.controller ?? ''] === 'Win32'
)
const sanityPlan = computed(() => context.value?.plans[context.value.sanityMode])
const essencePlan = computed(() => context.value?.plans[context.value.essenceMode])
const dailyTasks = [
  ...Object.values(taskGroups)
    .flat()
    .filter(name => name !== 'SeizeDeliveryJobs'),
  'ProtocolSpace',
  'AutoEssence',
]
const dailyOnce = computed(() => {
  const tasks: unknown[] = JSON.parse((task.value.DailyOnceTasks as string) ?? '[]')
  return tasks.filter((task): task is string => typeof task === 'string' && task.length > 0)
})
const dailyChoices = computed(() => choices([...new Set([...dailyTasks, ...dailyOnce.value])], t))

async function reload() {
  const revision = ++contextRevision
  const next = await panel.editor<Context>()
  const pathChanged = context.value?.path !== next.path
  if (revision !== contextRevision) return
  context.value = next
  if (!next.path || pathChanged) resources.value = undefined
  if (next.path && !resources.value) {
    const options = await panel.options()
    if (revision === contextRevision) resources.value = options
  }
}

onMounted(
  () =>
    void panel.run(async () => {
      await panel.initialize()
      await reload()
    })
)
watch(config, (_next, previous) => {
  if (Object.keys(previous).length) void reload().catch(panel.report)
})

function save(field: string, value: ConfigValue) {
  return panel.run(() => panel.saveField('Task', field, value))
}

function saveProtocol(field: string, value: ConfigValue) {
  const changes = [{ group: 'Task', field, value }]
  if (
    field === 'SanityTaskType' ||
    ['OperatorProgression', 'WeaponProgression', 'CrisisDrills'].includes(field)
  ) {
    const type = field === 'SanityTaskType' ? String(value) : field
    const selected = field === 'SanityTaskType' ? task.value[type] : value
    if (!rewardTasks.has(String(selected))) {
      changes.push({ group: 'Task', field: 'RewardsSetOption', value: 'RewardsSetA' })
    }
  }
  return panel.run(() => panel.save(changes))
}

function routeValues(group: RouteGroup) {
  return (
    (task.value[group.configKey] as string[] | null) ??
    resources
      .value!.autoCollectGroups.filter(item => item.configKey === group.configKey)
      .flatMap(item => item.defaultCases)
  )
}

function saveRoutes(group: RouteGroup, selected: ConfigValue) {
  const existing = new Set(group.options.map(option => option.value))
  const next = [
    ...new Set([
      ...routeValues(group).filter(value => !existing.has(value)),
      ...(selected as string[]),
    ]),
  ]
  return save(group.configKey, next)
}

function importConfig() {
  return panel.run(async () => {
    if (!(await panel.confirm(t('importConfirm'), true))) return
    await panel.editor('POST', '/import')
    status.value = t('importDone')
  })
}
</script>

<template>
  <p v-if="working || status" role="status">{{ working ? t('working') : status }}</p>
  <div v-if="error" class="actions">
    <p class="field-error" role="alert">{{ error }}</p>
    <button type="button" :disabled="working" @click="panel.run(reload)">{{ t('retry') }}</button>
  </div>
  <fieldset v-if="context" :disabled="disabled" class="stack">
    <div v-if="context.path && context.base !== 'native'" class="actions">
      <button type="button" @click="importConfig">{{ t('importConfig') }}</button>
    </div>
    <p v-if="!context.path" class="hint">{{ t('chooseInstall') }}</p>
    <p v-else-if="!supported" class="hint">{{ t('win32Only') }}</p>
    <p v-if="resources?.servers.length && supported" class="hint">
      {{ t('servers') }} ·
      {{
        resources.servers
          .map(option => option.label + (option.label === option.value ? '' : ` (${option.value})`))
          .join(' / ')
      }}
    </p>
    <template v-if="context.quickConfig && supported">
      <section class="card stack">
        <h2>{{ t('tasks') }}</h2>
        <div v-for="(names, group) in taskGroups" :key="group" class="stack">
          <h3>{{ t(group) }}</h3>
          <div class="grid">
            <ConfigField
              v-for="name in names"
              :key="name"
              :label="t(name)"
              type="checkbox"
              :value="task['If' + name]"
              @change="save('If' + name, $event)"
            />
          </div>
        </div>
        <div v-if="task.IfSeizeDeliveryJobs" class="grid">
          <ConfigField
            :label="t('SeizeDeliveryJobsCommissionSource')"
            :options="choices(['Unlimited', 'WulingCity', 'TestArea'], t)"
            :value="task.SeizeDeliveryJobsCommissionSource"
            @change="save('SeizeDeliveryJobsCommissionSource', $event)"
          />
          <ConfigField
            :label="t('SeizeDeliveryJobsReward')"
            type="number"
            :min="0"
            :max="9999"
            :step="0.1"
            :value="task.SeizeDeliveryJobsReward"
            @change="save('SeizeDeliveryJobsReward', $event)"
          />
        </div>
        <ConfigField
          :label="t('DailyOnceTasks')"
          :value="dailyOnce"
          :groups="[{ label: t('tasks'), value: 'tasks', options: dailyChoices }]"
          @change="save('DailyOnceTasks', JSON.stringify($event))"
        />
      </section>
      <section class="card stack">
        <h2>{{ t('ProtocolSpace') }}</h2>
        <ConfigField
          :label="t('ProtocolSpace')"
          type="checkbox"
          :value="task.IfProtocolSpace"
          @change="save('IfProtocolSpace', $event)"
        />
        <template v-if="task.IfProtocolSpace">
          <template v-if="context.sanityStrategy === 'Inventory'">
            <InventoryFields
              v-if="resources?.inventory"
              :panel="panel"
              :inventory="resources.inventory"
              :defaults="context.inventoryDefaults"
              @change="save"
            />
            <p v-else class="hint">{{ t('inventoryUnavailable') }}</p>
          </template>
          <template v-else-if="context.sanityStrategy === 'MAS'">
            <p v-if="sanityPlan" class="hint">{{ t('activePlan') }} · {{ sanityPlan.name }}</p>
            <div v-if="sanityPlan?.key.SanityTaskType !== 'Essence'" class="grid">
              <SanityField
                v-for="field in ['SanityTaskType', 'CurrentTask', 'RewardsSetOption'] as const"
                :key="field"
                :field="field"
                :value="sanityPlan?.key ?? task"
                :resources="resources"
                mode="protocol"
                :disabled="!!sanityPlan"
                :t="t"
                @change="saveProtocol"
              />
            </div>
            <p v-else class="hint">{{ t('Essence') }}</p>
          </template>
          <p v-else class="hint">{{ t('nativeHint') }}</p>
        </template>
      </section>
      <section class="card stack">
        <h2>{{ t('AutoEssence') }}</h2>
        <ConfigField
          :label="t('AutoEssence')"
          type="checkbox"
          :value="task.IfAutoEssence"
          @change="save('IfAutoEssence', $event)"
        />
        <template v-if="task.IfAutoEssence">
          <p v-if="essencePlan" class="hint">{{ t('activePlan') }} · {{ essencePlan.name }}</p>
          <p v-if="context.essenceMode === 'Native'" class="hint">{{ t('nativeHint') }}</p>
          <p v-else-if="essencePlan && essencePlan.key.SanityTaskType !== 'Essence'" class="hint">
            {{ t('noEssenceToday') }}
          </p>
          <div v-else class="grid">
            <SanityField
              v-for="field in ['AutoEssenceMenu', 'CurrentTask'] as const"
              :key="field"
              :field="field"
              :value="essencePlan?.key ?? task"
              :resources="resources"
              mode="essence"
              :disabled="!!essencePlan"
              :t="t"
              @change="save"
            />
          </div>
        </template>
      </section>
      <section class="card stack">
        <h2>{{ t('AutoCollect') }}</h2>
        <ConfigField
          :label="t('AutoCollect')"
          type="checkbox"
          :value="task.IfAutoCollect"
          @change="save('IfAutoCollect', $event)"
        />
        <template v-if="task.IfAutoCollect">
          <ConfigField
            :label="t('AutoCollectMode')"
            :options="choices(['Distributed', 'Concentrated'], t)"
            :value="task.AutoCollectMode"
            @change="save('AutoCollectMode', $event)"
          />
          <p v-if="!resources?.autoCollectGroups.length" class="hint">
            {{ t('routesUnavailable') }}
          </p>
          <div v-else class="grid">
            <ConfigField
              v-for="group in resources.autoCollectGroups"
              :key="`${group.regionLabel}:${group.value}`"
              :label="[group.regionLabel, group.label].filter(Boolean).join(' · ')"
              :groups="[group]"
              :value="routeValues(group)"
              @change="saveRoutes(group, $event)"
            />
          </div>
        </template>
      </section>
    </template>
  </fieldset>
</template>
