export type Option = { label: string; value: string }
export type OptionGroup = { label: string; value: string; options: Option[] }
export type RouteGroup = OptionGroup & {
  configKey: 'AutoCollectRoutes' | 'AutoCollectCommonRoutes'
  regionLabel: string
  defaultCases: string[]
}
export type ResourceOptions = {
  controllers: Option[]
  controllerTypes: Record<string, string>
  launchGameControllers: string[]
  gameSettingControllers: string[]
  originalResolution: string | null
  originalDisplayType: string | null
  servers: Option[]
  crisisDrills: Option[]
  essenceLocations: Option[]
  essenceMenus: Option[]
  essenceTargetWeaponGroups: OptionGroup[]
  autoCollectGroups: RouteGroup[]
  inventory: { description: string; inputs: Option[]; claimModes: Option[] } | null
}

export const weekdays = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
]

export const protocolTypes = ['OperatorProgression', 'WeaponProgression', 'CrisisDrills']
export const protocolTasks: Record<string, string[]> = {
  OperatorProgression: ['OperatorEXP', 'Promotions', 'T-Creds', 'SkillUp'],
  WeaponProgression: ['WeaponEXP', 'WeaponTune'],
}
export const rewardTasks = new Set(['OperatorEXP', 'Promotions', 'SkillUp', 'WeaponTune'])
export const rewardOptions = ['RewardsSetA', 'RewardsSetB']

export const taskGroups = {
  Daily: [
    'DijiangRewards',
    'CreditShoppingN2',
    'VisitFriends',
    'DailyRewards',
    'EnvironmentMonitoring',
    'ResourceRecycleStation',
    'PullCountCalculator',
  ],
  Collection: [
    'AutoEcoFarm',
    'TrialOfSwordmancy',
    'SellProduct',
    'AutoSell',
    'AutoStockStaple',
    'AutoStockpile',
  ],
  Delivery: ['DeliveryJobs', 'SeizeDeliveryJobs'],
}

export function choices(values: readonly string[], t: (key: string) => string): Option[] {
  return values.map(value => ({ label: t(value), value }))
}
