/** Ink's gateway client: `@slave-agent/shared/gateway-client` wired to the `slave --tui` launcher (its
 *  bootstrap, `SLAVE_TUI_*` overrides, launch tool-progress pin, i18n and crash-log breadcrumbs). */
import { type ConnectGateway, GatewayClient as SharedGatewayClient } from '@slave-agent/shared/gateway-client'
import { WebSocket as UndiciWebSocket } from 'undici'

import { t } from './i18n/runtime.js'
import { launchToolProgress } from './launchOptions.js'
import { recordParentLifecycle } from './lib/parentLog.js'
import { bootstrapLocalGateway, isTerminalBootstrapFailure } from './localGatewayBootstrap.js'

const STARTUP_TIMEOUT_MS = Math.max(5000, parseInt(process.env.SLAVE_TUI_STARTUP_TIMEOUT_MS ?? '15000', 10) || 15000)
const REQUEST_TIMEOUT_MS = Math.max(30000, parseInt(process.env.SLAVE_TUI_RPC_TIMEOUT_MS ?? '120000', 10) || 120000)

const envUrl = (name: 'SLAVE_TUI_GATEWAY_URL' | 'SLAVE_TUI_SIDECAR_URL') => () => process.env[name]?.trim() || null

export class GatewayClient extends SharedGatewayClient {
  constructor(bootstrap: ConnectGateway = bootstrapLocalGateway) {
    super({
      attachUrl: envUrl('SLAVE_TUI_GATEWAY_URL'),
      connect: bootstrap,
      fallbackWebSocket: UndiciWebSocket as unknown as typeof WebSocket,
      terminalConnectFailure: error =>
        isTerminalBootstrapFailure(error.message) ? error.message.match(/^gateway unavailable: .*$/m)?.[0] : undefined,
      onLifecycle: recordParentLifecycle,
      requestTimeoutMs: REQUEST_TIMEOUT_MS,
      sidecarUrl: envUrl('SLAVE_TUI_SIDECAR_URL'),
      startupTimeoutMs: STARTUP_TIMEOUT_MS,
      text: t,
      toolProgress: () => launchToolProgress()
    })
  }
}
