<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, shallowRef, watch } from 'vue'
import ConfigField from './ConfigField.vue'
import { usePanel, type ConfigValue } from './bridge'
import { choices, type Option, type ResourceOptions } from './options'

const panel = usePanel()
const { config, configuredSecrets, disabled, working, error, status, t, value } = panel
type Context = { path: string | null; executable: string | null; launcher: string | null }
type Update = {
  taskId: string
  status: 'pending' | 'running' | 'success' | 'error' | 'cancelled'
  log: string
}
const context = shallowRef<Context>()
const resources = shallowRef<ResourceOptions>()
const update = shallowRef<Update | null>(null)
const confirmingStop = ref<string>()
const detected = ref('')
const launcherError = ref('')
const logDirectories = ref<string[]>([])
const updateRunning = computed(
  () => update.value?.status === 'pending' || update.value?.status === 'running'
)
let pollTimer: number | undefined
let disposed = false
let contextRevision = 0
let updateRevision = 0

const controller = computed(() => String(value('Game', 'ControllerType') ?? ''))
const win32 = computed(() => resources.value?.controllerTypes[controller.value] === 'Win32')
const native = computed(
  () => resources.value?.launchGameControllers.includes(controller.value) ?? false
)
const launchMode = computed(() =>
  value('Game', 'LaunchMode') === 'Client'
    ? native.value
      ? 'MaaEnd'
      : 'MAS'
    : value('Game', 'LaunchMode')
)
const launchOptions = computed(() =>
  choices(native.value ? ['MaaEnd', 'Launcher', 'MAS'] : ['MAS', 'Launcher'], t)
)
const canSetResolution = computed(() =>
  launchMode.value === 'MaaEnd'
    ? native.value
    : resources.value?.gameSettingControllers.includes(controller.value)
)

type Field = {
  group: string
  name: string
  type?: 'checkbox' | 'number'
  min?: number
  max?: number
  options?: string[]
}
const runFields: Field[] = [
  { group: 'Run', name: 'AccountSwitchMethod', options: ['MAAEND', 'MAS'] },
  { group: 'Run', name: 'TaskTransitionMethod', options: ['NoAction', 'ExitGame'] },
  { group: 'Run', name: 'ProxyTimesLimit', type: 'number', min: 0, max: 9999 },
  ...['HardTimeLimit', 'RunTimeLimit', 'RunTimesLimit'].map(name => ({
    group: 'Run',
    name,
    type: 'number' as const,
    min: 1,
    max: 9999,
  })),
  { group: 'Run', name: 'IfSaveLogBundle', type: 'checkbox' },
]
const gameFields = computed<Field[]>(() => {
  if (!win32.value) return []
  const fields: Field[] = [
    { group: 'Game', name: 'Arguments' },
    { group: 'Game', name: 'WaitTime', type: 'number', min: 60, max: 9999 },
    { group: 'Game', name: 'CloseOnFinish', type: 'checkbox' },
  ]
  if (canSetResolution.value)
    fields.push({ group: 'Game', name: 'SetResolution', type: 'checkbox' })
  if (launchMode.value === 'MaaEnd')
    fields.push({ group: 'Game', name: 'AutoHDR', options: ['Unchanged', 'Disable', 'Enable'] })
  if (value('Game', 'CloseOnFinish')) {
    fields.push(
      { group: 'Game', name: 'RestoreAutoHDR', options: ['Unchanged', 'Disable', 'Enable'] },
      {
        group: 'Game',
        name: 'RestoreResolution',
        options: ['Off', 'Original', '1920x1080', '2560x1440', '3840x2160', 'Custom'],
      }
    )
    const resolution = value('Game', 'RestoreResolution')
    if (resolution !== 'Off' && resolution !== 'Original') {
      fields.push({ group: 'Game', name: 'RestoreDisplayType', options: ['Window', 'Fullscreen'] })
    }
    if (resolution === 'Custom') {
      for (const name of ['RestoreResolutionWidth', 'RestoreResolutionHeight']) {
        fields.push({ group: 'Game', name, type: 'number', min: 1, max: 16384 })
      }
    }
  }
  return fields
})

function fieldOptions(field: Field): Option[] | undefined {
  return (
    field.options &&
    choices(field.options, key =>
      key === 'MAS' && field.group === 'Run' ? t('masAccountSwitch') : t(key)
    )
  )
}

async function reload() {
  const revision = ++contextRevision
  const next = await panel.editor<Context>()
  if (revision !== contextRevision) return
  const previous = context.value
  if (previous?.path !== next.path || previous?.executable !== next.executable)
    resources.value = undefined
  context.value = next
  if (next.path && !resources.value) {
    const options = await panel.options()
    if (revision === contextRevision) resources.value = options
  }
}

async function refreshUpdate() {
  const revision = ++updateRevision
  const current = await panel.editor<Update | null>('GET', '/update')
  if (disposed || revision !== updateRevision) return
  update.value = current
  if (!updateRunning.value || current?.taskId !== confirmingStop.value)
    confirmingStop.value = undefined
  window.clearTimeout(pollTimer)
  if (updateRunning.value) {
    pollTimer = window.setTimeout(() => void refreshUpdate().catch(panel.report), 1500)
  }
}

onMounted(
  () =>
    void panel.run(async () => {
      await panel.initialize()
      await refreshUpdate()
      await reload()
    })
)
watch(config, (_next, previous) => {
  if (Object.keys(previous).length) void reload().catch(panel.report)
})
watch(
  () =>
    win32.value && launchMode.value !== 'MaaEnd' && !context.value?.launcher
      ? context.value?.executable
      : null,
  async (executable, _previous, onCleanup) => {
    detected.value = ''
    launcherError.value = ''
    if (!executable) return
    let current = true
    onCleanup(() => {
      current = false
    })
    try {
      const result = await panel.detectLauncher()
      if (current) detected.value = result.launcher_path
    } catch (cause) {
      if (current) launcherError.value = cause instanceof Error ? cause.message : String(cause)
    }
  }
)
onScopeDispose(() => {
  disposed = true
  window.clearTimeout(pollTimer)
})

function save(group: string, field: string, next: ConfigValue) {
  return panel.run(async () => {
    if (
      field === 'AccountSwitchMethod' &&
      next === 'MAS' &&
      !(await panel.confirm(t('masAccountWarning')))
    )
      return
    if (
      field === 'PackageMode' &&
      next === 'incremental' &&
      !(await panel.confirm(t('incrementalWarning')))
    )
      return
    await panel.saveField(group, field, next)
  })
}

function chooseController(next: ConfigValue) {
  return panel.run(async () => {
    const changes = [{ group: 'Game', field: 'ControllerType', value: next }]
    if (resources.value?.controllerTypes[String(next)] === 'Adb') {
      changes.push(
        { group: 'Game', field: 'Path', value: null },
        { group: 'Game', field: 'Arguments', value: '' },
        { group: 'Game', field: 'WaitTime', value: 60 }
      )
    }
    await panel.save(changes)
  })
}

function detectLauncher() {
  return panel.run(async () => {
    launcherError.value = ''
    detected.value = (await panel.detectLauncher()).launcher_path
  })
}

function chooseLauncher(clear = false) {
  return panel.run(async () => {
    const path = clear ? null : await panel.pickPath('file', context.value?.launcher ?? undefined)
    if (!clear && !path) return
    context.value = await panel.editor<Context>('PUT', '/launcher', { path })
    detected.value = ''
  })
}

function selectLogPath() {
  return panel.run(async () => {
    const path = await panel.pickPath('folder', value('Run', 'LogBundlePath') as string | undefined)
    if (path) await panel.saveField('Run', 'LogBundlePath', path)
  })
}

type LogBundle = { directories: string[]; needsDirectory: boolean; incompleteCount: number }
function getLogs() {
  return panel.run(async () => {
    let result = await panel.request<LogBundle>('POST', '/maaend/log-bundle', {})
    if (result.needsDirectory) {
      const outputDirectory = await panel.pickPath('folder')
      if (!outputDirectory) return
      result = await panel.request<LogBundle>('POST', '/maaend/log-bundle', { outputDirectory })
    }
    logDirectories.value = result.directories
    if (!result.directories.length) status.value = t('noLogs')
    if (result.incompleteCount) status.value = `${t('logsIncomplete')} ${result.incompleteCount}`
  })
}

function startUpdate() {
  return panel.run(async () => {
    if (!(await panel.confirm(t('checkUpdateConfirm')))) return
    await panel.editor('POST', '/update')
    await refreshUpdate()
  })
}

function stopUpdate(taskId: string) {
  return panel.run(async () => {
    await panel.editor('POST', `/update/${taskId}/stop`)
    confirmingStop.value = undefined
    await refreshUpdate()
  })
}
</script>

<template>
  <p v-if="working || status" role="status">{{ working ? t('working') : status }}</p>
  <div v-if="error" class="actions">
    <p class="field-error" role="alert">{{ error }}</p>
    <button
      type="button"
      :disabled="working"
      @click="
        panel.run(async () => {
          await reload()
          await refreshUpdate()
        })
      "
    >
      {{ t('retry') }}
    </button>
  </div>
  <fieldset class="stack" :disabled="disabled">
    <section class="card stack">
      <h2>{{ t('game') }}</h2>
      <ConfigField
        v-if="resources"
        :label="t('ControllerType')"
        :value="controller || null"
        :options="resources.controllers"
        :placeholder="t('select')"
        @change="chooseController"
      />
      <p v-else class="hint">{{ t('chooseInstall') }}</p>
      <template v-if="win32">
        <div class="grid">
          <ConfigField
            :label="t('LaunchMode')"
            :value="launchMode"
            :options="launchOptions"
            @change="save('Game', 'LaunchMode', $event)"
          />
          <ConfigField
            v-for="field in gameFields"
            :key="field.name"
            :label="t(field.name)"
            :type="field.type"
            :min="field.min"
            :max="field.max"
            :options="fieldOptions(field)"
            :value="value(field.group, field.name)"
            @change="save(field.group, field.name, $event)"
          />
        </div>
        <p
          v-if="value('Game', 'RestoreResolution') === 'Original' && resources?.originalResolution"
          class="hint"
        >
          {{ resources.originalResolution }}
          {{ resources.originalDisplayType ? t(resources.originalDisplayType) : '' }}
        </p>
        <div class="stack">
          <p v-if="context?.launcher || detected" class="hint">
            {{ t('LauncherPath') }} · {{ context?.launcher || detected }}
          </p>
          <p v-if="launcherError" class="field-error" role="alert">{{ launcherError }}</p>
          <div v-if="context?.executable" class="actions">
            <button type="button" @click="chooseLauncher()">{{ t('pickLauncher') }}</button>
            <button v-if="context.launcher" type="button" @click="chooseLauncher(true)">
              {{ t('clearLauncher') }}
            </button>
            <button v-else-if="launchMode !== 'MaaEnd'" type="button" @click="detectLauncher">
              {{ t('detectLauncher') }}
            </button>
          </div>
          <div v-else class="actions">
            <p class="hint">{{ t('bindGame') }}</p>
            <button type="button" @click="panel.run(reload)">{{ t('refresh') }}</button>
          </div>
        </div>
      </template>
    </section>
    <section class="card stack">
      <h2>{{ t('run') }}</h2>
      <div class="grid">
        <ConfigField
          v-for="field in runFields"
          :key="field.name"
          :label="t(field.name)"
          :type="field.type"
          :min="field.min"
          :max="field.max"
          :options="fieldOptions(field)"
          :value="value(field.group, field.name)"
          @change="save(field.group, field.name, $event)"
        />
      </div>
      <div v-if="value('Run', 'IfSaveLogBundle')" class="actions">
        <span class="hint">{{ value('Run', 'LogBundlePath') || t('defaultLogPath') }}</span>
        <button type="button" @click="selectLogPath">{{ t('LogBundlePath') }}</button>
        <button
          v-if="value('Run', 'LogBundlePath')"
          type="button"
          @click="save('Run', 'LogBundlePath', null)"
        >
          {{ t('reset') }}
        </button>
      </div>
      <div>
        <button type="button" @click="getLogs">{{ t('getLogs') }}</button>
        <ul v-if="logDirectories.length">
          <li v-for="directory in logDirectories" :key="directory">{{ directory }}</li>
        </ul>
      </div>
    </section>
    <section class="card stack">
      <h2>{{ t('programUpdate') }}</h2>
      <ConfigField
        :label="t('TakeoverEnabled')"
        type="checkbox"
        :value="value('Update', 'TakeoverEnabled')"
        @change="save('Update', 'TakeoverEnabled', $event)"
      />
      <div v-if="value('Update', 'TakeoverEnabled')" class="grid">
        <ConfigField
          :label="t('PackageMode')"
          :options="choices(['full', 'incremental'], t)"
          :value="value('Update', 'PackageMode')"
          @change="save('Update', 'PackageMode', $event)"
        />
        <ConfigField
          :label="t('Channel')"
          :options="choices(['stable', 'beta'], t)"
          :value="value('Update', 'Channel')"
          @change="save('Update', 'Channel', $event)"
        />
        <ConfigField
          :label="t('MirrorChyanCDK')"
          type="password"
          :placeholder="
            t(
              configuredSecrets.includes('Update.MirrorChyanCDK') ? 'configuredSecret' : 'globalCdk'
            )
          "
          @change="save('Update', 'MirrorChyanCDK', $event)"
        />
        <div v-if="configuredSecrets.includes('Update.MirrorChyanCDK')" class="actions">
          <button type="button" @click="save('Update', 'MirrorChyanCDK', '')">
            {{ t('reset') }}
          </button>
        </div>
      </div>
    </section>
  </fieldset>
  <section v-if="win32 || update" class="card stack">
    <h2>{{ t('gameUpdate') }}</h2>
    <fieldset class="grid" :disabled="disabled || updateRunning">
      <ConfigField
        :label="t('IfAutoUpdate')"
        type="checkbox"
        :value="value('Game', 'IfAutoUpdate')"
        @change="save('Game', 'IfAutoUpdate', $event)"
      />
      <ConfigField
        :label="t('UpdateTimeLimit')"
        type="number"
        :min="1"
        :max="9999"
        :value="value('Game', 'UpdateTimeLimit')"
        @change="save('Game', 'UpdateTimeLimit', $event)"
      />
    </fieldset>
    <div class="actions">
      <button
        v-if="updateRunning"
        type="button"
        :disabled="working"
        @click="confirmingStop = update?.taskId"
      >
        {{ t('stopUpdate') }}
      </button>
      <button v-else-if="win32" type="button" :disabled="disabled" @click="startUpdate">
        {{ t('checkUpdate') }}
      </button>
      <span v-if="update" role="status">{{ t(update.status) }}</span>
    </div>
    <div v-if="confirmingStop" class="actions">
      <span>{{ t('stopUpdateConfirm') }}</span>
      <button type="button" :disabled="working" @click="stopUpdate(confirmingStop)">
        {{ t('stopUpdate') }}
      </button>
      <button type="button" :disabled="working" @click="confirmingStop = undefined">
        {{ t('cancel') }}
      </button>
    </div>
    <pre v-if="update?.log" tabindex="0">{{ update.log }}</pre>
  </section>
</template>
