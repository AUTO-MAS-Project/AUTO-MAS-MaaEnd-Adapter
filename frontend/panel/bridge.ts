import { computed, ref, shallowRef } from 'vue'
import locale from '../../src/auto_mas_maaend_adapter/i18n/zh-CN.json'
import type { ResourceOptions } from './options'

type Value = string | number | boolean | null
export type ConfigValue = Value | ConfigValue[] | { [key: string]: ConfigValue }
type Config = Record<string, Record<string, ConfigValue>>
type Snapshot = { config: Config; configuredSecrets: string[] }
type Target =
  | { kind: 'script' | 'setup' | 'user'; scriptId: string; userId: string | null }
  | { kind: 'plan'; planId: string }
type State = { locale: string; i18nRevision: number; locked: boolean; busy: boolean }
type Method = 'GET' | 'POST' | 'PUT'
type Change = { group: string; field: string; value: ConfigValue }
type Reply<T> = {
  ok: boolean
  status: number
  data: T & { code?: number; message?: string; detail?: string }
}

declare function connectPanel(): {
  getContext(): Promise<State & Snapshot & { target: Target }>
  translate(keys: string[]): Promise<{ messages: Record<string, string> }>
  request<T>(method: Method, path: string, body?: unknown): Promise<Reply<T>>
  saveConfig(changes: Change[], phase: 'commit'): Promise<{ ok: boolean; message?: string }>
  pickPath(options: {
    mode: 'file' | 'folder'
    defaultPath?: string
    filters?: { name: string; extensions: string[] }[]
  }): Promise<{ path: string | null }>
  confirm(options: { message: string; danger?: boolean }): Promise<{ confirmed: boolean }>
  onConfigReloaded(callback: (snapshot: Snapshot) => void): () => void
  onStateChange(callback: (state: State) => void): () => void
}

const prefix = 'plugins.maaend_adapter.'
const labels = Object.keys(locale).filter(key => key.startsWith(prefix + 'panel.'))
const translationKeys = labels.map(key => key.slice(prefix.length))

export function usePanel() {
  const panel = connectPanel()
  const config = shallowRef<Config>({})
  const configuredSecrets = shallowRef<string[]>([])
  const state = shallowRef<State>()
  const target = shallowRef<Target>()
  const messages = shallowRef<Record<string, string>>({})
  const working = ref(false)
  const error = ref('')
  const status = ref('')
  const disabled = computed(
    () => !state.value || state.value.locked || state.value.busy || working.value
  )
  let translationVersion = 0

  function t(key: string) {
    const full = 'panel.' + key
    return messages.value[full] ?? (locale as Record<string, string>)[prefix + full] ?? key
  }

  async function applyState(next: State) {
    const previous = state.value
    state.value = next
    if (previous?.locale === next.locale && previous.i18nRevision === next.i18nRevision) return
    const version = ++translationVersion
    const { messages: translated } = await panel.translate(translationKeys)
    if (version === translationVersion) {
      messages.value = translated
      document.documentElement.lang = next.locale
    }
  }

  function report(cause: unknown) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }

  async function initialize() {
    const initial = await panel.getContext()
    target.value = initial.target
    function applyConfig(next: Snapshot) {
      config.value = next.config
      configuredSecrets.value = next.configuredSecrets
    }
    applyConfig(initial)
    panel.onConfigReloaded(applyConfig)
    panel.onStateChange(next => void applyState(next).catch(report))
    await applyState(initial)
  }

  async function run(operation: () => Promise<void>) {
    if (working.value) return
    working.value = true
    error.value = ''
    status.value = ''
    try {
      await operation()
    } catch (cause) {
      report(cause)
    } finally {
      working.value = false
    }
  }

  async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
    const { ok, status, data } = await panel.request<T>(method, path, body)
    if (!ok || (data?.code !== undefined && data.code !== 200)) {
      const message = data?.message || data?.detail
      throw new Error(typeof message === 'string' ? message : `HTTP ${status}`)
    }
    return data
  }

  function editor<T>(method: Method = 'GET', suffix = '', body?: unknown): Promise<T> {
    const active = target.value!
    const path =
      active.kind === 'plan'
        ? `plan/${active.planId}`
        : active.userId
          ? `user/${active.scriptId}/${active.userId}`
          : `script/${active.scriptId}`
    return request<T>(method, `/editor/${path}${suffix}`, body)
  }

  async function save(changes: Change[]) {
    const result = await panel.saveConfig(changes, 'commit')
    if (!result.ok) throw new Error(result.message)
  }

  function saveField(group: string, field: string, value: ConfigValue) {
    return save([{ group, field, value }])
  }

  function value(group: string, field: string) {
    return config.value[group]?.[field]
  }

  async function pickPath(mode: 'file' | 'folder', defaultPath?: string) {
    const filters = mode === 'file' ? [{ name: 'EXE', extensions: ['exe'] }] : undefined
    return (await panel.pickPath({ mode, defaultPath, filters })).path
  }

  async function confirm(message: string, danger = false) {
    return (await panel.confirm({ message, danger })).confirmed
  }

  return {
    config,
    configuredSecrets,
    disabled,
    working,
    error,
    status,
    t,
    initialize,
    report,
    request,
    editor,
    save,
    saveField,
    value,
    pickPath,
    confirm,
    run,
    options: () => {
      const active = target.value!
      return active.kind === 'plan'
        ? editor<ResourceOptions>('GET', '/options')
        : request<ResourceOptions>('POST', '/maaend/options', { scriptId: active.scriptId })
    },
    detectLauncher: () => {
      const active = target.value!
      if (active.kind === 'plan') throw new Error('Invalid script target')
      return request<{ launcher_path: string }>(
        'GET',
        `/maaend/launcher-path?scriptId=${encodeURIComponent(active.scriptId)}`
      )
    },
  }
}

export type Panel = ReturnType<typeof usePanel>

export const input = (event: Event) => event.target as HTMLInputElement
export const selection = (event: Event) => event.target as HTMLSelectElement
