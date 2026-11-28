<script setup lang="ts">
import { useId } from 'vue'
import { input, selection, type ConfigValue } from './bridge'
import type { Option, OptionGroup } from './options'

const props = defineProps<{
  label: string
  value?: ConfigValue
  options?: Option[]
  groups?: OptionGroup[]
  type?: 'checkbox' | 'text' | 'number' | 'password'
  placeholder?: string
  min?: number
  max?: number
  step?: number
  nullable?: boolean
  disabled?: boolean
}>()
const emit = defineEmits<{ change: [value: ConfigValue] }>()
const id = useId()

function change(event: Event) {
  const field = input(event)
  if (props.type === 'number' && !field.checkValidity()) {
    field.reportValidity()
    return
  }
  if (props.type === 'password' && !field.value) return
  emit(
    'change',
    props.type === 'number'
      ? field.valueAsNumber
      : props.nullable && !field.value
        ? null
        : field.value
  )
  if (props.type === 'password') field.value = ''
}

function select(event: Event) {
  const field = selection(event)
  if (!field.multiple) {
    const next = field.value
    field.value = typeof props.value === 'string' ? props.value : ''
    emit('change', next)
    return
  }
  const next = Array.from(field.selectedOptions, item => item.value)
  for (const option of field.options) {
    option.selected = Array.isArray(props.value) && props.value.includes(option.value)
  }
  emit('change', next)
}
</script>

<template>
  <label v-if="type === 'checkbox'" class="switch-tile" :title="label">
    <input
      type="checkbox"
      :checked="value === true"
      :disabled="disabled"
      @change="emit('change', input($event).checked)"
    />
    {{ label }}
  </label>
  <div v-else>
    <label :for="id">{{ label }}</label>
    <select v-if="groups" :id="id" multiple :disabled="disabled" @change="select">
      <optgroup v-for="group in groups" :key="group.value" :label="group.label">
        <option
          v-for="option in group.options"
          :key="option.value"
          :value="option.value"
          :selected="Array.isArray(value) && value.includes(option.value)"
        >
          {{ option.label }}
        </option>
      </optgroup>
    </select>
    <select v-else-if="options" :id="id" :value="value ?? ''" :disabled="disabled" @change="select">
      <option
        v-if="typeof value === 'string' && !options.some(option => option.value === value)"
        :value="value"
        disabled
      >
        {{ value }}
      </option>
      <option v-else-if="value == null" value="" disabled>{{ placeholder }}</option>
      <option v-for="option in options" :key="option.value" :value="option.value">
        {{ option.label }}
      </option>
    </select>
    <input
      v-else
      :key="String(value)"
      :id="id"
      :type="type ?? 'text'"
      :value="value ?? ''"
      :min="min"
      :max="max"
      :step="step"
      :placeholder="placeholder"
      :required="type === 'number'"
      :disabled="disabled"
      @change="change"
    />
  </div>
</template>
