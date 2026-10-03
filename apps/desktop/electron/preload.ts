import { contextBridge, ipcRenderer, webFrame, webUtils } from 'electron'

import type { DesktopProfileRoute } from './desktop-profile'
import type { HudModifierApi, HudModifierStatus } from './hud-modifier-types'
import { customWindowControlsEnabled } from './window-controls'

// Which translucency the OS can back. Asked synchronously because the renderer
// needs it before its first paint, and answered by main because deciding it
// needs `os.release()` — a sandboxed preload may only require electron, events,
// timers and url, so importing node:os here throws before contextBridge runs
// and takes the ENTIRE bridge down with it (window.slaveDesktop undefined =>
// "Desktop IPC bridge is unavailable"). No reply means no glass, which degrades
// to an ordinary opaque window rather than a page thinned over nothing.
const translucencySupport = ipcRenderer.sendSync('slave:translucency:support')
const hudWindowing = ipcRenderer.sendSync('slave:hud:windowing')
const hudNativeDrag = hudWindowing?.nativeDrag === true

const launchFlags: { localModels?: boolean; guestOnboarding?: boolean } | undefined =
  ipcRenderer.sendSync('slave:feature-flags')

// Local, sanitized skin payload for the first renderer theme paint. This does
// not wait on `gateway.ready`, so an unreachable remote primary cannot force
// the built-in palette over the skin configured on this machine.
const localSkin = ipcRenderer.sendSync('slave:skin:local')

import { unwrapExpectedNotFound } from './api-expected-404'

contextBridge.exposeInMainWorld('slaveDesktop', {
  glassSupported: translucencySupport?.glass === true,
  translucencySupported: translucencySupport?.translucency === true,
  // Launch-flag fact: the app was started with --local, so the renderer may
  // show the local-models surfaces. Static for the window's lifetime.
  localModelsEnabled: launchFlags?.localModels === true,
  // Launch-flag fact: the Nous free tier is on for this launch
  // (SLAVE_GUEST_ONBOARDING=1 or --guest-onboarding). Read-only; the same
  // decision is stamped onto every backend the app spawns.
  guestOnboardingEnabled: launchFlags?.guestOnboarding === true,
  localSkin: localSkin && typeof localSkin === 'object' ? localSkin : null,
  getConnection: (profile, opts) => ipcRenderer.invoke('slave:connection', profile, opts),
  // Loopback origin that hosts YouTube's player for the file:// renderer.
  getEmbedHostOrigin: () => ipcRenderer.invoke('slave:embed-host:origin'),
  // Registry-scoped backend resolution: { connectionId, profile } → descriptor.
  getConnectionFor: payload => ipcRenderer.invoke('slave:connection:for', payload),
  getProfileRoutes: profiles => ipcRenderer.invoke('slave:plugin-profile-routes', profiles),
  revalidateConnection: () => ipcRenderer.invoke('slave:connection:revalidate'),
  touchBackend: (profile, options) => ipcRenderer.invoke('slave:backend:touch', profile, options),
  getPoolLimits: () => ipcRenderer.invoke('slave:pool-limits:get'),
  setPoolLimits: limits => ipcRenderer.invoke('slave:pool-limits:set', limits),
  getGatewayWsUrl: profile => ipcRenderer.invoke('slave:gateway:ws-url', profile),
  // Registry-scoped fresh WS URL: { connectionId, profile } → result shape of
  // getGatewayWsUrl, minted against that connection's backend.
  getGatewayWsUrlFor: payload => ipcRenderer.invoke('slave:gateway:ws-url-for', payload),
  // Union agent roster across every registered connection.
  getAgentRoster: () => ipcRenderer.invoke('slave:agents:roster'),
  openSessionWindow: (sessionId, opts) => ipcRenderer.invoke('slave:window:openSession', sessionId, opts),
  openSessionInTerminal: (sessionId, opts) => ipcRenderer.invoke('slave:window:openInTerminal', sessionId, opts),
  openWindow: (options?: DesktopProfileRoute) => ipcRenderer.invoke('slave:window:openInstance', options),
  openBrowserWindow: tabId => ipcRenderer.invoke('slave:window:openBrowser', tabId),
  windowRelay: {
    send: payload => ipcRenderer.send('slave:window:relay', payload),
    onMessage: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('slave:window:relay', listener)

      return () => ipcRenderer.removeListener('slave:window:relay', listener)
    }
  },
  onBrowserPopoutClosed: callback => {
    const listener = (_event, tabId) => callback(tabId)
    ipcRenderer.on('slave:browser-popout:closed', listener)

    return () => ipcRenderer.removeListener('slave:browser-popout:closed', listener)
  },
  claimAmbientCue: key => ipcRenderer.invoke('slave:ambient:claim', key),
  windowControls: {
    custom: customWindowControlsEnabled(),
    minimize: () => ipcRenderer.send('slave:window-control', 'minimize'),
    toggleMaximize: () => ipcRenderer.send('slave:window-control', 'toggle-maximize'),
    close: () => ipcRenderer.send('slave:window-control', 'close')
  },
  wakeIndicator: {
    getState: () => ipcRenderer.invoke('slave:wake-indicator:get'),
    setState: state => ipcRenderer.send('slave:wake-indicator:set', state),
    onState: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('slave:wake-indicator:state', listener)

      return () => ipcRenderer.removeListener('slave:wake-indicator:state', listener)
    }
  },
  chatOnboarding: {
    grow: request => ipcRenderer.send('slave:chat-onboarding:grow', request),
    soloBoot: () => ipcRenderer.send('slave:chat-onboarding:solo-boot')
  },
  petOverlay: {
    // Main renderer → main process: window lifecycle + drag. `request` is
    // `{ bounds, screen }`; resolves with the screen bounds it actually used.
    open: request => ipcRenderer.invoke('slave:pet-overlay:open', request),
    close: () => ipcRenderer.invoke('slave:pet-overlay:close'),
    setBounds: bounds => ipcRenderer.send('slave:pet-overlay:set-bounds', bounds),
    setIgnoreMouse: ignore => ipcRenderer.send('slave:pet-overlay:ignore-mouse', ignore),
    // Flip the overlay focusable (and focus it) while the composer needs keys.
    setFocusable: focusable => ipcRenderer.send('slave:pet-overlay:set-focusable', focusable),
    // Main renderer → overlay (forwarded by main): push the latest pet state.
    pushState: payload => ipcRenderer.send('slave:pet-overlay:state', payload),
    // Overlay → main renderer (forwarded by main): pop back in / composer submit.
    control: payload => ipcRenderer.send('slave:pet-overlay:control', payload),
    // Overlay subscribes to state pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('slave:pet-overlay:state', listener)

      return () => ipcRenderer.removeListener('slave:pet-overlay:state', listener)
    },
    // Main renderer subscribes to overlay control messages.
    onControl: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('slave:pet-overlay:control', listener)

      return () => ipcRenderer.removeListener('slave:pet-overlay:control', listener)
    }
  },
  // HUD mode: the chrome-free floating chat. A full app renderer (own gateway)
  // sized as a floating bar, so it mounts the real composer. Main owns the
  // window; `onChanged` keeps every window's toggle truthful.
  hud: {
    nativeDrag: hudNativeDrag,
    windowing: {
      clientPlacement: hudWindowing?.clientPlacement !== false,
      controlDrag: hudWindowing?.controlDrag === true,
      nativeDrag: hudNativeDrag,
      solid: hudWindowing?.solid === true,
      workspaceTransfer: hudWindowing?.workspaceTransfer === true
    },
    open: request => ipcRenderer.invoke('slave:hud:open', request),
    close: () => ipcRenderer.invoke('slave:hud:close'),
    setIgnoreMouse: ignore => ipcRenderer.send('slave:hud:ignore-mouse', ignore),
    beginMove: () => ipcRenderer.send('slave:hud:begin-move'),
    endMove: () => ipcRenderer.send('slave:hud:end-move'),
    moveBy: delta => ipcRenderer.send('slave:hud:move-by', delta),
    setWorkspaceTransfer: transferring => ipcRenderer.send('slave:hud:workspace-transfer', transferring),
    setBounds: bounds => ipcRenderer.send('slave:hud:set-bounds', bounds),
    resetLayout: () => ipcRenderer.invoke('slave:hud:reset-layout'),
    // Whether the band covers the window below the bar. Main pairs it with the
    // user's translucency setting to decide the native frost (macOS vibrancy /
    // Windows 11 DWM backdrop) — see hudFrostFor.
    setFrost: showing => ipcRenderer.invoke('slave:hud:frost', showing),
    // The HUD tells main which session it is on; main hands that back to the
    // app window when the HUD closes, so the app can re-home onto it.
    setSession: sessionId => ipcRenderer.send('slave:hud:session', sessionId),
    onGoto: callback => {
      const listener = (_event, sessionId) => callback(sessionId)
      ipcRenderer.on('slave:hud:goto', listener)

      return () => ipcRenderer.removeListener('slave:hud:goto', listener)
    },
    onChanged: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('slave:hud:changed', listener)

      return () => ipcRenderer.removeListener('slave:hud:changed', listener)
    },
    // Linux only, and silent elsewhere: where the cursor is, in page
    // coordinates, or null when it has left the window. Stands in for the
    // mousemove that `setIgnoreMouseEvents(true, { forward: true })` delivers on
    // macOS and Windows but not here.
    onCursor: callback => {
      const listener = (_event, point) => callback(point)
      ipcRenderer.on('slave:hud:cursor', listener)

      return () => ipcRenderer.removeListener('slave:hud:cursor', listener)
    },
    // Main's game-overlay watch: whether a fullscreen app (a game) is under
    // the HUD, so the renderer can step back to the low-opacity overlay
    // treatment while one owns the screen.
    onGameOverlay: callback => {
      const listener = (_event, state) => callback(state)
      ipcRenderer.on('slave:hud:game-overlay', listener)

      return () => ipcRenderer.removeListener('slave:hud:game-overlay', listener)
    }
  },
  hudModifier: {
    getSettings: () => ipcRenderer.invoke('slave:hud-modifier:settings:get'),
    setEnabled: enabled => ipcRenderer.invoke('slave:hud-modifier:settings:set', enabled),
    openPermissionSettings: () => ipcRenderer.invoke('slave:hud-modifier:permission'),
    onStatus: callback => {
      const listener = (_event: Electron.IpcRendererEvent, status: HudModifierStatus) => callback(status)
      ipcRenderer.on('slave:hud-modifier:status', listener)

      return () => ipcRenderer.removeListener('slave:hud-modifier:status', listener)
    }
  } satisfies HudModifierApi,
  // macOS native screenshot gesture; captures require a main-issued request.
  screenshot:
    process.platform === 'darwin'
      ? {
          getSettings: () => ipcRenderer.invoke('slave:screenshot:settings:get'),
          setEnabled: enabled => ipcRenderer.invoke('slave:screenshot:settings:set', enabled),
          openPermissionSettings: kind => ipcRenderer.invoke('slave:screenshot:permission', kind),
          capture: requestId => ipcRenderer.invoke('slave:screenshot:capture', requestId),
          onStatus: callback => {
            const listener = (_event, status) => callback(status)
            ipcRenderer.on('slave:screenshot:status', listener)

            return () => ipcRenderer.removeListener('slave:screenshot:status', listener)
          },
          onRequest: callback => {
            const channel = 'slave:screenshot:request'
            const listener = (_event, requestId) => callback(requestId)

            if (ipcRenderer.listenerCount(channel) === 0) {
              ipcRenderer.send('slave:screenshot:subscribe', true)
            }

            ipcRenderer.on(channel, listener)

            return () => {
              ipcRenderer.removeListener(channel, listener)

              if (ipcRenderer.listenerCount(channel) === 0) {
                ipcRenderer.send('slave:screenshot:subscribe', false)
              }
            }
          }
        }
      : undefined,
  // Quick Entry: the global-hotkey mini composer window. Main owns the OS
  // shortcut + the persisted preference; the quick window only captures text
  // and hands it back, and the primary renderer submits it through the normal
  // prompt path.
  quickEntry: {
    getSettings: () => ipcRenderer.invoke('slave:quick-entry:settings:get'),
    setSettings: patch => ipcRenderer.invoke('slave:quick-entry:settings:set', patch),
    // Invoke returns the delivery result so the draft is not lost (#85590).
    submit: payload => ipcRenderer.invoke('slave:quick-entry:submit', payload),
    // Main cannot invoke the primary renderer, so it receives this ack (#85590).
    ackSubmit: (correlationId, result) => ipcRenderer.send('slave:quick-entry:ack', { correlationId, result }),
    dismiss: () => ipcRenderer.send('slave:quick-entry:dismiss'),
    // Primary renderer → main → quick window: gateway connection state + the
    // recent-session options the target picker offers. Main caches the latest
    // payload so a freshly spawned quick window starts from truth.
    pushState: payload => ipcRenderer.send('slave:quick-entry:state', payload),
    // Quick window subscribes to those pushes.
    onState: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('slave:quick-entry:state', listener)

      return () => ipcRenderer.removeListener('slave:quick-entry:state', listener)
    },
    // Main → primary renderer: a submit captured by the quick window.
    onSubmit: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('slave:quick-entry:submit', listener)

      return () => ipcRenderer.removeListener('slave:quick-entry:submit', listener)
    },
    // Main → quick window: you were just summoned (reset draft + refocus).
    onShown: callback => {
      const listener = () => callback()
      ipcRenderer.on('slave:quick-entry:shown', listener)

      return () => ipcRenderer.removeListener('slave:quick-entry:shown', listener)
    },
    // Main → quick window: the outcome of a submit whose relay already timed
    // out. Delivery is now KNOWN — reconcile the unknown state instead of
    // leaving the user to resend a prompt that may already be delivered.
    onLateResult: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('slave:quick-entry:late-result', listener)

      return () => ipcRenderer.removeListener('slave:quick-entry:late-result', listener)
    }
  },
  getBootProgress: () => ipcRenderer.invoke('slave:boot-progress:get'),
  getConnectionConfig: profile => ipcRenderer.invoke('slave:connection-config:get', profile),
  saveConnectionConfig: payload => ipcRenderer.invoke('slave:connection-config:save', payload),
  applyConnectionConfig: payload => ipcRenderer.invoke('slave:connection-config:apply', payload),
  testConnectionConfig: payload => ipcRenderer.invoke('slave:connection-config:test', payload),
  // Opt-in OS-keychain encryption for stored gateway secrets (default off —
  // see secret-storage-policy.ts). get never touches the OS keychain.
  getSecretStorageEncryption: () => ipcRenderer.invoke('slave:secret-storage:get'),
  setSecretStorageEncryption: (on: boolean) => ipcRenderer.invoke('slave:secret-storage:set', on),
  // v2 multi-connection registry: named agent sources (local / remote / cloud / ssh).
  connections: {
    list: () => ipcRenderer.invoke('slave:connections:list'),
    save: payload => ipcRenderer.invoke('slave:connections:save', payload),
    remove: id => ipcRenderer.invoke('slave:connections:remove', id),
    setPrimary: id => ipcRenderer.invoke('slave:connections:set-primary', id),
    setLaunchMode: mode => ipcRenderer.invoke('slave:connections:set-launch-mode', mode),
    setLastUsed: id => ipcRenderer.invoke('slave:connections:set-last-used', id),
    test: id => ipcRenderer.invoke('slave:connections:test', id),
    updateManaged: id => ipcRenderer.invoke('slave:connections:update-managed', id),
    // Fan out `slave update` to every eligible registered connection.
    // Optional excludeIds skips rows the caller updates through another path.
    updateAll: options => ipcRenderer.invoke('slave:connections:update-all', options),
    // Registry lifecycle push (main → renderer): a connection was removed or
    // materially edited, so secondaries scoped to it must be disposed (and,
    // for edits, re-dialed at the new target).
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('slave:connections:changed', listener)

      return () => ipcRenderer.removeListener('slave:connections:changed', listener)
    }
  },
  sshConfigHosts: () => ipcRenderer.invoke('slave:ssh-config:hosts'),
  sshResolveHost: host => ipcRenderer.invoke('slave:ssh-config:resolve', host),
  probeConnectionConfig: remoteUrl => ipcRenderer.invoke('slave:connection-config:probe', remoteUrl),
  // `options` lets a registry-editor draft sign in BEFORE it is saved: the
  // main process settles the draft's connection id up front so the login
  // window writes into the per-connection cookie jar the saved entry will
  // read (not the legacy shared jar an unsaved URL would fall back to).
  oauthLoginConnectionConfig: (remoteUrl, options) =>
    ipcRenderer.invoke('slave:connection-config:oauth-login', remoteUrl, options),
  oauthLogoutConnectionConfig: remoteUrl => ipcRenderer.invoke('slave:connection-config:oauth-logout', remoteUrl),
  // Slave Cloud: one portal login powers discovery + silent per-agent sign-in
  // (cloud-auto-discovery Phase 3).
  cloud: {
    status: () => ipcRenderer.invoke('slave:cloud:status'),
    login: () => ipcRenderer.invoke('slave:cloud:login'),
    logout: () => ipcRenderer.invoke('slave:cloud:logout'),
    discover: org => ipcRenderer.invoke('slave:cloud:discover', org),
    agentSignIn: dashboardUrl => ipcRenderer.invoke('slave:cloud:agent-sign-in', dashboardUrl)
  },
  profile: {
    getDefault: () => ipcRenderer.invoke('slave:profile:default:get'),
    setDefault: (route: DesktopProfileRoute) => ipcRenderer.invoke('slave:profile:default:set', route),
    onDefaultChanged: (callback: (route: DesktopProfileRoute | null) => void) => {
      const listener = (_event: Electron.IpcRendererEvent, route: DesktopProfileRoute | null) => callback(route)
      ipcRenderer.on('slave:profile:default:changed', listener)

      return () => ipcRenderer.removeListener('slave:profile:default:changed', listener)
    },
    get: () => ipcRenderer.invoke('slave:profile:get'),
    remember: name => ipcRenderer.invoke('slave:profile:remember', name),
    set: name => ipcRenderer.invoke('slave:profile:set', name)
  },
  // The handler resolves an expected 404 with a sentinel instead of rejecting
  // (Electron logs a stack for every rejected invoke). Turn it back into the
  // rejection the renderer expects — see electron/api-expected-404.ts.
  api: request => ipcRenderer.invoke('slave:api', request).then(unwrapExpectedNotFound),
  notify: payload => ipcRenderer.invoke('slave:notify', payload),
  claimStartupLatency: () => ipcRenderer.invoke('slave:startup-latency:claim'),
  requestMicrophoneAccess: () => ipcRenderer.invoke('slave:requestMicrophoneAccess'),
  readWindowBelow: () => ipcRenderer.invoke('slave:window:readBelow'),
  readFileDataUrl: filePath => ipcRenderer.invoke('slave:readFileDataUrl', filePath),
  readFileDataUrlForAttach: filePath => ipcRenderer.invoke('slave:readFileDataUrlForAttach', filePath),
  dataUrlReadMax: {
    get: () => ipcRenderer.invoke('slave:data-url-read-max:get'),
    set: maxMb => ipcRenderer.invoke('slave:data-url-read-max:set', maxMb)
  },
  readFileText: filePath => ipcRenderer.invoke('slave:readFileText', filePath),
  readPluginSource: (filePath: string) => ipcRenderer.invoke('slave:readPluginSource', filePath),
  selectPaths: options => ipcRenderer.invoke('slave:selectPaths', options),
  selectSavePath: options => ipcRenderer.invoke('slave:selectSavePath', options),
  writeClipboard: text => ipcRenderer.invoke('slave:writeClipboard', text),
  readClipboard: () => ipcRenderer.invoke('slave:readClipboard'),
  saveGatewayFile: payload => ipcRenderer.invoke('slave:saveGatewayFile', payload),
  saveImageFromUrl: url => ipcRenderer.invoke('slave:saveImageFromUrl', url),
  contextMenuEdit: command => ipcRenderer.invoke('slave:context-menu:edit', command),
  contextMenuCopyImage: () => ipcRenderer.invoke('slave:context-menu:copy-image'),
  contextMenuSpellcheck: action => ipcRenderer.invoke('slave:context-menu:spellcheck', action),
  contextMenuGuestAddWord: payload => ipcRenderer.invoke('slave:context-menu:guest-add-word', payload),
  onContextMenuSpellcheck: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:context-menu-spellcheck', listener)

    return () => ipcRenderer.removeListener('slave:context-menu-spellcheck', listener)
  },
  saveImageBuffer: (data, ext, name) => ipcRenderer.invoke('slave:saveImageBuffer', { data, ext, name }),
  capturePreview: payload => ipcRenderer.invoke('slave:capturePreview', payload),
  savePastedText: text => ipcRenderer.invoke('slave:savePastedText', { text }),
  saveClipboardImage: () => ipcRenderer.invoke('slave:saveClipboardImage'),
  getPathForFile: file => {
    try {
      return webUtils.getPathForFile(file) || ''
    } catch {
      return ''
    }
  },
  normalizePreviewTarget: (target, baseDir) => ipcRenderer.invoke('slave:normalizePreviewTarget', target, baseDir),
  watchPreviewFile: url => ipcRenderer.invoke('slave:watchPreviewFile', url),
  watchDirectory: dir => ipcRenderer.invoke('slave:watchDirectory', dir),
  stopPreviewFileWatch: id => ipcRenderer.invoke('slave:stopPreviewFileWatch', id),
  setActiveWork: payload => ipcRenderer.send('slave:active-work', payload),
  setTitleBarTheme: payload => ipcRenderer.send('slave:titlebar-theme', payload),
  setNativeTheme: mode => ipcRenderer.send('slave:native-theme', mode),
  setTranslucency: payload => ipcRenderer.send('slave:translucency', payload),
  setKeepAwake: on => ipcRenderer.send('slave:keep-awake', on),
  minimizeToTray: {
    get: () => ipcRenderer.invoke('slave:minimize-to-tray:get'),
    set: on => ipcRenderer.invoke('slave:minimize-to-tray:set', on),
    onChanged: callback => {
      const listener = (_event, status) => callback(status)
      ipcRenderer.on('slave:minimize-to-tray:changed', listener)

      return () => ipcRenderer.removeListener('slave:minimize-to-tray:changed', listener)
    }
  },
  setDisableF12: blocked => ipcRenderer.send('slave:devtools:disable-f12', blocked),
  setF12ShortcutActive: active => ipcRenderer.send('slave:f12ShortcutActive', Boolean(active)),
  onF12Shortcut: callback => {
    const listener = (_event, input) => callback(input)
    ipcRenderer.on('slave:f12-shortcut', listener)

    return () => ipcRenderer.removeListener('slave:f12-shortcut', listener)
  },
  setPreviewShortcutActive: active => ipcRenderer.send('slave:previewShortcutActive', Boolean(active)),
  setPreviewGuestHidden: (webContentsId, hidden) =>
    ipcRenderer.send('slave:preview-guest-hidden', { webContentsId, hidden: Boolean(hidden) }),
  openExternal: url => ipcRenderer.invoke('slave:openExternal', url),
  mcpOauth: {
    // One-shot loopback listener for MCP OAuth against remote backends: bind
    // on this machine, hand redirectUri to mcp.servers.oauth.start, then wait
    // for the provider redirect and relay code/state via oauth.callback.
    listen: () => ipcRenderer.invoke('slave:mcp-oauth:listen'),
    wait: (id, timeoutMs) => ipcRenderer.invoke('slave:mcp-oauth:wait', id, timeoutMs),
    cancel: id => ipcRenderer.invoke('slave:mcp-oauth:cancel', id)
  },
  openPreviewInBrowser: url => ipcRenderer.invoke('slave:openPreviewInBrowser', url),
  reachPreviewUrl: url => ipcRenderer.invoke('slave:preview:reach', url),
  setActiveConnectionRoute: route => ipcRenderer.send('slave:connection:active-route', route),
  fetchLinkTitle: url => ipcRenderer.invoke('slave:fetchLinkTitle', url),
  resolveFavicon: url => ipcRenderer.invoke('slave:resolveFavicon', url),
  sanitizeWorkspaceCwd: cwd => ipcRenderer.invoke('slave:workspace:sanitize', cwd),
  settings: {
    getDefaultProjectDir: () => ipcRenderer.invoke('slave:setting:defaultProjectDir:get'),
    setDefaultProjectDir: dir => ipcRenderer.invoke('slave:setting:defaultProjectDir:set', dir),
    pickDefaultProjectDir: () => ipcRenderer.invoke('slave:setting:defaultProjectDir:pick')
  },
  zoom: {
    // Current zoom of this window, as { level, percent }.
    get: () => ipcRenderer.invoke('slave:zoom:get'),
    // Synchronous zoom factor (1 = 100%). Coordinate math needs it in the
    // same tick as the event it converts, so no IPC round-trip here.
    factor: () => webFrame.getZoomFactor(),
    setPercent: percent => ipcRenderer.send('slave:zoom:set-percent', percent),
    // Fires on every zoom change, including the Ctrl/Cmd +/-/0 shortcuts,
    // so the settings UI can stay in sync with the keyboard.
    onChanged: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('slave:zoom:changed', listener)

      return () => ipcRenderer.removeListener('slave:zoom:changed', listener)
    }
  },
  revealLogs: () => ipcRenderer.invoke('slave:logs:reveal'),
  getRecentLogs: () => ipcRenderer.invoke('slave:logs:recent'),
  // Fire-and-forget: persists a renderer error-boundary catch (with component
  // stack) to desktop.log so crashes survive the window (#79428).
  reportRendererError: report => ipcRenderer.send('slave:logs:renderer-error', report),
  logLine: (line: string): void => ipcRenderer.send('slave:logs:renderer-line', line),
  readDir: dirPath => ipcRenderer.invoke('slave:fs:readDir', dirPath),
  gitRoot: startPath => ipcRenderer.invoke('slave:fs:gitRoot', startPath),
  revealPath: targetPath => ipcRenderer.invoke('slave:fs:reveal', targetPath),
  openDir: dirPath => ipcRenderer.invoke('slave:fs:openDir', dirPath),
  desktopPluginsRoot: () => ipcRenderer.invoke('slave:fs:desktopPluginsRoot'),
  reconcileDesktopPlugins: () => ipcRenderer.invoke('slave:fs:reconcileDesktopPlugins'),
  logsRoot: (profile?: string) => ipcRenderer.invoke('slave:fs:logsRoot', profile),
  renamePath: (targetPath, newName) => ipcRenderer.invoke('slave:fs:rename', targetPath, newName),
  writeTextFile: (filePath, content) => ipcRenderer.invoke('slave:fs:writeText', filePath, content),
  trashPath: targetPath => ipcRenderer.invoke('slave:fs:trash', targetPath),
  git: {
    worktreeList: repoPath => ipcRenderer.invoke('slave:git:worktreeList', repoPath),
    worktreeAdd: (repoPath, options) => ipcRenderer.invoke('slave:git:worktreeAdd', repoPath, options),
    worktreeRemove: (repoPath, worktreePath, options) =>
      ipcRenderer.invoke('slave:git:worktreeRemove', repoPath, worktreePath, options),
    branchSwitch: (repoPath, branch) => ipcRenderer.invoke('slave:git:branchSwitch', repoPath, branch),
    branchList: repoPath => ipcRenderer.invoke('slave:git:branchList', repoPath),
    baseBranchList: repoPath => ipcRenderer.invoke('slave:git:baseBranchList', repoPath),
    repoStatus: repoPath => ipcRenderer.invoke('slave:git:repoStatus', repoPath),
    fileDiff: (repoPath, filePath) => ipcRenderer.invoke('slave:git:fileDiff', repoPath, filePath),
    scanRepos: (roots, options) => ipcRenderer.invoke('slave:git:scanRepos', roots, options),
    review: {
      list: (repoPath, scope, baseRef) => ipcRenderer.invoke('slave:git:review:list', repoPath, scope, baseRef),
      diff: (repoPath, filePath, scope, baseRef, staged) =>
        ipcRenderer.invoke('slave:git:review:diff', repoPath, filePath, scope, baseRef, staged),
      stage: (repoPath, filePath) => ipcRenderer.invoke('slave:git:review:stage', repoPath, filePath),
      unstage: (repoPath, filePath) => ipcRenderer.invoke('slave:git:review:unstage', repoPath, filePath),
      revert: (repoPath, filePath) => ipcRenderer.invoke('slave:git:review:revert', repoPath, filePath),
      revParse: (repoPath, ref) => ipcRenderer.invoke('slave:git:review:revParse', repoPath, ref),
      commit: (repoPath, message, push) => ipcRenderer.invoke('slave:git:review:commit', repoPath, message, push),
      commitContext: repoPath => ipcRenderer.invoke('slave:git:review:commitContext', repoPath),
      push: repoPath => ipcRenderer.invoke('slave:git:review:push', repoPath),
      shipInfo: repoPath => ipcRenderer.invoke('slave:git:review:shipInfo', repoPath),
      prList: (repoPath, branches, numbers) =>
        ipcRenderer.invoke('slave:git:review:prList', repoPath, branches, numbers),
      createPr: repoPath => ipcRenderer.invoke('slave:git:review:createPr', repoPath)
    }
  },
  terminal: {
    attach: id => ipcRenderer.invoke('slave:terminal:attach', id),
    cwd: id => ipcRenderer.invoke('slave:terminal:cwd', id),
    dispose: id => ipcRenderer.invoke('slave:terminal:dispose', id),
    resize: (id, size) => ipcRenderer.invoke('slave:terminal:resize', id, size),
    start: options => ipcRenderer.invoke('slave:terminal:start', options),
    write: (id, data) => ipcRenderer.invoke('slave:terminal:write', id, data),
    onData: (id, callback) => {
      const channel = `slave:terminal:${id}:data`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    },
    onExit: (id, callback) => {
      const channel = `slave:terminal:${id}:exit`
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on(channel, listener)

      return () => ipcRenderer.removeListener(channel, listener)
    }
  },
  onClosePreviewRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('slave:close-preview-requested', listener)

    return () => ipcRenderer.removeListener('slave:close-preview-requested', listener)
  },
  onPreviewNav: callback => {
    const listener = (_event, command) => callback(command)
    ipcRenderer.on('slave:preview-nav', listener)

    return () => ipcRenderer.removeListener('slave:preview-nav', listener)
  },
  onOpenFolderRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('slave:open-folder-requested', listener)

    return () => ipcRenderer.removeListener('slave:open-folder-requested', listener)
  },
  onOpenUpdatesRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('slave:open-updates', listener)

    return () => ipcRenderer.removeListener('slave:open-updates', listener)
  },
  onDeepLink: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:deep-link', listener)

    return () => ipcRenderer.removeListener('slave:deep-link', listener)
  },
  signalDeepLinkReady: () => ipcRenderer.invoke('slave:deep-link-ready'),
  probePluginRepo: payload => ipcRenderer.invoke('slave:plugin:probe', payload),
  installDesktopPlugin: payload => ipcRenderer.invoke('slave:plugin:installDesktop', payload),
  removeDesktopPlugin: payload => ipcRenderer.invoke('slave:plugin:removeDesktop', payload),
  onWindowStateChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:window-state-changed', listener)

    return () => ipcRenderer.removeListener('slave:window-state-changed', listener)
  },
  onFocusSession: callback => {
    const listener = (_event, sessionId) => callback(sessionId)
    ipcRenderer.on('slave:focus-session', listener)

    return () => ipcRenderer.removeListener('slave:focus-session', listener)
  },
  onNotificationAction: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:notification-action', listener)

    return () => ipcRenderer.removeListener('slave:notification-action', listener)
  },
  onNotificationActivate: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:notification-activate', listener)

    return () => ipcRenderer.removeListener('slave:notification-activate', listener)
  },
  onExternalOpenFailed: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:external-open-failed', listener)

    return () => ipcRenderer.removeListener('slave:external-open-failed', listener)
  },
  onPreviewFileChanged: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:preview-file-changed', listener)

    return () => ipcRenderer.removeListener('slave:preview-file-changed', listener)
  },
  onBackendExit: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:backend-exit', listener)

    return () => ipcRenderer.removeListener('slave:backend-exit', listener)
  },
  // Cooperative pool retirement (main → renderer): the pooled backend under
  // `poolKey` is being stopped for a foreground open. Park that scope; do not
  // redial into the slot it vacated.
  onPoolBackendRetiring: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:pool:retiring', listener)

    return () => ipcRenderer.removeListener('slave:pool:retiring', listener)
  },
  // Soft gateway-mode apply finished tearing down the primary backend. Renderer
  // should wipe session lists + re-dial without a window reload.
  onConnectionApplied: callback => {
    const listener = () => callback()
    ipcRenderer.on('slave:connection:applied', listener)

    return () => ipcRenderer.removeListener('slave:connection:applied', listener)
  },
  onPowerResume: callback => {
    const listener = () => callback()
    ipcRenderer.on('slave:power-resume', listener)

    return () => ipcRenderer.removeListener('slave:power-resume', listener)
  },
  // AC ↔ battery transitions; renderers slow their backstop polls on battery.
  getOnBattery: () => ipcRenderer.invoke('slave:power-battery:get'),
  onBatteryChanged: callback => {
    const listener = (_event, onBattery) => callback(Boolean(onBattery))
    ipcRenderer.on('slave:power-battery', listener)

    return () => ipcRenderer.removeListener('slave:power-battery', listener)
  },
  onBootProgress: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:boot-progress', listener)

    return () => ipcRenderer.removeListener('slave:boot-progress', listener)
  },
  // First-launch bootstrap progress -- emitted by the install.ps1 stage
  // runner in main.ts (apps/desktop/electron/bootstrap-runner.ts).
  // Renderer's install overlay subscribes to live events and queries the
  // current snapshot via getBootstrapState() to recover after a devtools
  // reload mid-bootstrap.
  getBootstrapState: () => ipcRenderer.invoke('slave:bootstrap:get'),
  probeLocalBackend: () => ipcRenderer.invoke('slave:local-backend:probe'),
  continueBootstrapLocal: () => ipcRenderer.invoke('slave:bootstrap:continue-local'),
  recycleBackend: profile => ipcRenderer.invoke('slave:backend:recycle', profile),
  resetBootstrap: () => ipcRenderer.invoke('slave:bootstrap:reset'),
  repairBootstrap: () => ipcRenderer.invoke('slave:bootstrap:repair'),
  cancelBootstrap: () => ipcRenderer.invoke('slave:bootstrap:cancel'),
  onBootstrapEvent: callback => {
    const listener = (_event, payload) => callback(payload)
    ipcRenderer.on('slave:bootstrap:event', listener)

    return () => ipcRenderer.removeListener('slave:bootstrap:event', listener)
  },
  getVersion: () => ipcRenderer.invoke('slave:version'),
  relaunchApp: () => ipcRenderer.invoke('slave:app:relaunch'),
  getMachineProfile: () => ipcRenderer.invoke('slave:machine:profile'),
  getRemoteDisplayReason: () => ipcRenderer.invoke('slave:get-remote-display-reason'),
  uninstall: {
    summary: () => ipcRenderer.invoke('slave:uninstall:summary'),
    run: mode => ipcRenderer.invoke('slave:uninstall:run', { mode })
  },
  updates: {
    check: opts => ipcRenderer.invoke('slave:updates:check', opts),
    apply: opts => ipcRenderer.invoke('slave:updates:apply', opts),
    getBranch: () => ipcRenderer.invoke('slave:updates:branch:get'),
    setBranch: name => ipcRenderer.invoke('slave:updates:branch:set', name),
    onProgress: callback => {
      const listener = (_event, payload) => callback(payload)
      ipcRenderer.on('slave:updates:progress', listener)

      return () => ipcRenderer.removeListener('slave:updates:progress', listener)
    },
    takePendingRun: () => ipcRenderer.invoke('slave:updates:metric:take'),
    ackPendingRun: sent => ipcRenderer.invoke('slave:updates:metric:ack', sent),
    onPendingRun: callback => {
      const listener = () => callback()
      ipcRenderer.on('slave:updates:metric:pending', listener)

      return () => ipcRenderer.removeListener('slave:updates:metric:pending', listener)
    }
  },
  desktopMetrics: {
    setEnabled: (on, profile) => ipcRenderer.invoke('slave:desktop-metrics:set-enabled', on, profile),
    takeRendererCrashes: () => ipcRenderer.invoke('slave:desktop-metrics:crash:take'),
    ackRendererCrashes: sent => ipcRenderer.invoke('slave:desktop-metrics:crash:ack', sent)
  },
  themes: {
    fetchMarketplace: id => ipcRenderer.invoke('slave:vscode-theme:fetch', id),
    searchMarketplace: query => ipcRenderer.invoke('slave:vscode-theme:search', query)
  },
  // Find-in-page (Ctrl/Cmd+F): delegates to Electron's
  // webContents.findInPage on the IPC sender's window so a Cmd+F pressed
  // in a secondary session window searches THAT window, not the primary.
  // `onFoundInPage` returns the unsubscribe fn; the renderer wires it via
  // `initFindInPageListener` in store/find-in-page.ts and tears it down
  // when the FindBar unmounts.
  findInPage: (query, options) => ipcRenderer.invoke('slave:find-in-page', query, options),
  stopFindInPage: () => ipcRenderer.invoke('slave:stop-find-in-page'),
  onFoundInPage: callback => {
    const listener = (_event, result) => callback(result)
    ipcRenderer.on('slave:found-in-page', listener)

    return () => ipcRenderer.removeListener('slave:found-in-page', listener)
  },
  // Main-process `before-input-event` forwards Ctrl/Cmd+F here so renderer
  // can open the FindBar even when the GTK compositor has already grabbed
  // the chord at the windowing layer (#81727).
  onOpenFindBarRequested: callback => {
    const listener = () => callback()
    ipcRenderer.on('slave:open-find-bar', listener)

    return () => ipcRenderer.removeListener('slave:open-find-bar', listener)
  }
})
