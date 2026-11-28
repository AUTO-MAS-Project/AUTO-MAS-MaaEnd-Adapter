<script setup lang="ts">
import { computed, ref } from 'vue'
import { type Panel, type ConfigValue, input } from './bridge'
import ConfigField from './ConfigField.vue'
import { INVENTORY_CATEGORIES, inventoryCategoryFor } from './inventoryCategories'
import {
  INVENTORY_TARGET_MAX,
  isInventoryTargetActive,
  readInventoryTargets,
} from './inventoryPlan'
import type { ResourceOptions } from './options'

const props = defineProps<{
  panel: Panel
  inventory: NonNullable<ResourceOptions['inventory']>
  defaults: Record<string, string>
}>()
const emit = defineEmits<{ change: [field: string, value: ConfigValue] }>()
const { t, value } = props.panel
const overrides = computed(() => readInventoryTargets(value('Task', 'SupplyPlanLimits') as string))
const targets = computed(() => ({ ...props.defaults, ...overrides.value }))
const unknown = computed(() =>
  Object.keys(overrides.value ?? {}).filter(
    key => !props.inventory.inputs.some(item => item.value === key)
  )
)
const search = ref('')
const plannedOnly = ref(false)
const groups = computed(() =>
  INVENTORY_CATEGORIES.map(({ key }) => ({
    key,
    inputs: props.inventory.inputs.filter(
      item =>
        inventoryCategoryFor(item.value) === key &&
        item.label.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase()) &&
        (!plannedOnly.value || isInventoryTargetActive(targets.value[item.value]))
    ),
  })).filter(group => group.inputs.length)
)

function setTarget(key: string, quantity: ConfigValue) {
  emit(
    'change',
    'SupplyPlanLimits',
    JSON.stringify({ ...overrides.value, [key]: String(quantity) })
  )
}

async function repair() {
  if (!(await props.panel.confirm(t('repairTargetsConfirm'), true))) return
  const known = Object.fromEntries(
    Object.entries(overrides.value ?? {}).filter(([name]) => !unknown.value.includes(name))
  )
  emit('change', 'SupplyPlanLimits', JSON.stringify(known))
}
</script>

<template>
  <div class="stack">
    <p v-if="inventory.description" class="hint">{{ inventory.description }}</p>
    <div class="grid">
      <ConfigField
        :label="t('ProtocolSpaceObtainModeClaim')"
        :options="inventory.claimModes"
        :value="value('Task', 'ProtocolSpaceObtainModeClaim')"
        @change="emit('change', 'ProtocolSpaceObtainModeClaim', $event)"
      />
      <ConfigField
        :label="t('IfAutoUseSpMedication')"
        type="checkbox"
        :value="value('Task', 'IfAutoUseSpMedication')"
        @change="emit('change', 'IfAutoUseSpMedication', $event)"
      />
    </div>
    <div v-if="overrides === null || unknown.length" class="actions">
      <span class="hint">{{
        overrides === null ? t('invalidTargets') : `${t('unknownTargets')} ${unknown.join(', ')}`
      }}</span>
      <button type="button" @click="repair">{{ t('repairTargets') }}</button>
    </div>
    <div class="grid">
      <ConfigField
        :label="t('searchMaterials')"
        :value="search"
        @change="search = String($event)"
      />
      <label class="switch-tile"
        ><input
          type="checkbox"
          :checked="plannedOnly"
          @change="plannedOnly = input($event).checked"
        />{{ t('plannedOnly') }}</label
      >
    </div>
    <details
      v-for="group in groups"
      :key="group.key"
      :open="group.key === groups[0]?.key || !!search"
    >
      <summary>{{ t(group.key) }}</summary>
      <div class="grid">
        <ConfigField
          v-for="item in group.inputs"
          :key="item.value"
          :label="item.label"
          type="number"
          :min="0"
          :max="Number(INVENTORY_TARGET_MAX)"
          :value="targets[item.value] ?? '0'"
          :disabled="overrides === null"
          @change="setTarget(item.value, $event)"
        />
      </div>
    </details>
  </div>
</template>
