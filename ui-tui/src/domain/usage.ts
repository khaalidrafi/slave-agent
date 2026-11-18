import type { Usage } from '@slave-agent/shared/gateway-events'

export { usageFromTick } from '@slave-agent/shared/usage-tick'

export const ZERO: Usage = { calls: 0, input: 0, output: 0, total: 0 }
