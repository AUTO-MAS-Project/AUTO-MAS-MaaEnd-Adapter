<script setup lang="ts">
import { computed, onMounted, ref, shallowRef, watch } from 'vue'
import { selection, usePanel, type ConfigValue } from './bridge'
import { rewardTasks, weekdays, type ResourceOptions } from './options'
import SanityField from './SanityField.vue'

const panel = usePanel()
const { config, disabled, error, t, working } = panel
type PlanContext = { mode: 'ALL' | 'Weekly' | 'Rotate'; rotateDays: number }
const context = shallowRef<PlanContext>()
const resources = shallowRef<ResourceOptions>()
const view = ref('config')
const contextPending = ref(false)
let contextRevision = 0
const fields = ['SanityTaskType', 'AutoEssenceMenu', 'CurrentTask', 'RewardsSetOption'] as const
type Field = (typeof fields)[number]
const slots = computed(() => {
  const mode = context.value?.mode
  const keys =
    mode === 'Weekly'
      ? weekdays
      : mode === 'Rotate'
        ? Array.from({ length: context.value!.rotateDays }, (_, index) => `Day${index + 1}`)
        : []
  return view.value === 'simple' && keys.length ? keys : ['ALL', ...keys]
})
const rows = computed(() => (view.value === 'config' ? fields : slots.value))
const columns = computed(() => (view.value === 'config' ? slots.value : fields))
const slotFor = (row: string, column: string) => (view.value === 'config' ? column : row)
const fieldFor = (row: string, column: string) => (view.value === 'config' ? row : column) as Field
const label = (key: string) => (key.startsWith('Day') ? `${t('day')} ${key.slice(3)}` : t(key))
const canEdit = (slot: string) => (context.value?.mode === 'ALL' ? slot === 'ALL' : slot !== 'ALL')
const keyFor = (slot: string) => (config.value[slot]?.Key as Record<string, ConfigValue>) ?? {}

async function reloadContext() {
  const revision = ++contextRevision
  contextPending.value = true
  try {
    const next = await panel.editor<PlanContext>()
    if (revision === contextRevision) context.value = next
  } finally {
    if (revision === contextRevision) contextPending.value = false
  }
}

async function refresh() {
  await reloadContext()
  resources.value = await panel.options()
}

onMounted(
  () =>
    void panel.run(async () => {
      await panel.initialize()
      await refresh()
    })
)
watch(config, (_next, previous) => {
  if (Object.keys(previous).length) void reloadContext().catch(panel.report)
})

function edit(slot: string, field: string, value: ConfigValue) {
  const next = { ...keyFor(slot), [field]: value }
  const type = next.SanityTaskType ?? 'OperatorProgression'
  // Key is a discriminated payload. Fields from the other task family must not be saved.
  const key: ConfigValue =
    type === 'Essence'
      ? {
          SanityTaskType: type,
          AutoEssenceMenu:
            next.AutoEssenceMenu ??
            (Array.isArray(next.AutoEssenceTargetWeapons) && next.AutoEssenceTargetWeapons.length
              ? 'Target'
              : 'Location'),
          AutoEssenceSpecifiedLocation: next.AutoEssenceSpecifiedLocation ?? '',
          AutoEssenceTargetWeapons: next.AutoEssenceTargetWeapons ?? [],
        }
      : {
          SanityTaskType: type,
          OperatorProgression: next.OperatorProgression ?? 'OperatorEXP',
          WeaponProgression: next.WeaponProgression ?? 'WeaponEXP',
          CrisisDrills: next.CrisisDrills ?? 'AdvancedProgression1',
          RewardsSetOption: rewardTasks.has(
            String(
              next[String(type)] ?? (type === 'OperatorProgression' ? 'OperatorEXP' : 'WeaponEXP')
            )
          )
            ? (next.RewardsSetOption ?? 'RewardsSetA')
            : 'RewardsSetA',
        }
  return panel.run(() => panel.saveField(slot, 'Key', key))
}
</script>

<template>
  <p v-if="working" role="status">{{ t('working') }}</p>
  <div v-if="error" class="actions">
    <p role="alert" class="field-error">{{ error }}</p>
    <button type="button" :disabled="working" @click="panel.run(refresh)">{{ t('retry') }}</button>
  </div>
  <fieldset v-if="context" :disabled="disabled || contextPending" class="stack">
    <label class="plan-view">
      {{ t('planView') }}
      <select :value="view" @change="view = selection($event).value">
        <option value="config">{{ t('planConfig') }}</option>
        <option value="simple">{{ t('planSimple') }}</option>
      </select>
    </label>
    <p
      v-if="
        resources &&
        !resources.crisisDrills.length &&
        !resources.essenceLocations.length &&
        !resources.essenceTargetWeaponGroups.length
      "
      class="hint"
    >
      {{ t('planOptionsEmpty') }}
    </p>
    <div class="plan-scroll" role="region" :aria-label="t('planConfig')" tabindex="0">
      <table class="plan-table">
        <thead>
          <tr>
            <th scope="col">{{ t(view === 'config' ? 'field' : 'time') }}</th>
            <th v-for="column in columns" :key="column" scope="col">{{ label(column) }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row">
            <th scope="row">{{ label(row) }}</th>
            <td v-for="column in columns" :key="column">
              <SanityField
                :field="fieldFor(row, column)"
                :value="keyFor(slotFor(row, column))"
                :resources="resources"
                :disabled="!canEdit(slotFor(row, column))"
                :t="t"
                @change="(field, value) => edit(slotFor(row, column), field, value)"
              />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </fieldset>
</template>
