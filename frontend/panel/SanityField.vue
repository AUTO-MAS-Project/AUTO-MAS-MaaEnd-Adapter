<script setup lang="ts">
import { computed } from 'vue'
import ConfigField from './ConfigField.vue'
import type { ConfigValue } from './bridge'
import {
  choices,
  protocolTasks,
  protocolTypes,
  rewardOptions,
  rewardTasks,
  type ResourceOptions,
} from './options'

const props = defineProps<{
  field: 'SanityTaskType' | 'AutoEssenceMenu' | 'CurrentTask' | 'RewardsSetOption'
  value: Record<string, ConfigValue>
  resources?: ResourceOptions
  mode?: 'protocol' | 'essence'
  t: (key: string) => string
  disabled?: boolean
}>()
const emit = defineEmits<{ change: [field: string, value: ConfigValue] }>()
const type = computed(() => {
  if (props.mode === 'essence') return 'Essence'
  const saved = String(props.value.SanityTaskType ?? 'OperatorProgression')
  return props.mode === 'protocol' && saved === 'Essence' ? 'OperatorProgression' : saved
})
const weapons = computed(() => (props.value.AutoEssenceTargetWeapons as string[] | undefined) ?? [])
const menu = computed(
  () => props.value.AutoEssenceMenu ?? (weapons.value.length ? 'Target' : 'Location')
)
const taskTypes = computed(() => [
  ...protocolTypes,
  ...(!props.mode &&
  (!props.resources ||
    props.resources.essenceLocations.length ||
    props.resources.essenceTargetWeaponGroups.length ||
    type.value === 'Essence')
    ? ['Essence']
    : []),
])
const taskField = computed(() => {
  if (type.value !== 'Essence') return type.value
  return menu.value === 'Target' ? 'AutoEssenceTargetWeapons' : 'AutoEssenceSpecifiedLocation'
})
const currentTask = computed(() => props.value[taskField.value])
const taskOptions = computed(() => {
  if (type.value === 'Essence') return props.resources?.essenceLocations ?? []
  if (type.value === 'CrisisDrills') return props.resources?.crisisDrills ?? []
  return choices(protocolTasks[type.value], props.t)
})
const weaponGroups = computed(() => {
  const groups = props.resources?.essenceTargetWeaponGroups ?? []
  const known = new Set(groups.flatMap(group => group.options.map(option => option.value)))
  const saved = weapons.value.filter(value => !known.has(value))
  return saved.length
    ? [
        ...groups,
        { value: 'saved', label: props.t('savedOptions'), options: choices(saved, value => value) },
      ]
    : groups
})
const hasRewards = computed(() => rewardTasks.has(String(currentTask.value)))
</script>

<template>
  <ConfigField
    v-if="field === 'SanityTaskType'"
    :label="t(field)"
    :value="type"
    :options="choices(taskTypes, t)"
    :disabled="disabled"
    @change="emit('change', field, $event)"
  />
  <ConfigField
    v-else-if="field === 'AutoEssenceMenu' && type === 'Essence'"
    :label="t(field)"
    :value="menu"
    :options="
      resources?.essenceMenus.length
        ? resources.essenceMenus
        : choices(['Random', 'Location', 'Target'], t)
    "
    :disabled="disabled"
    @change="emit('change', field, $event)"
  />
  <template v-else-if="field === 'CurrentTask'">
    <ConfigField
      v-if="type === 'Essence' && menu === 'Target'"
      :label="t(taskField)"
      :value="weapons"
      :groups="weaponGroups"
      :disabled="disabled || !resources"
      @change="emit('change', taskField, $event)"
    />
    <ConfigField
      v-else-if="type !== 'Essence' || menu !== 'Random'"
      :label="t(taskField)"
      :value="currentTask || null"
      :options="taskOptions"
      :placeholder="t('select')"
      :disabled="disabled || !taskOptions.length"
      @change="emit('change', taskField, $event)"
    />
  </template>
  <ConfigField
    v-else-if="field === 'RewardsSetOption' && hasRewards"
    :label="t(field)"
    :value="value.RewardsSetOption ?? 'RewardsSetA'"
    :options="choices(rewardOptions, t)"
    :disabled="disabled"
    @change="emit('change', field, $event)"
  />
</template>
