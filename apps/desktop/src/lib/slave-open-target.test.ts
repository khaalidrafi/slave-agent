import { describe, expect, it } from 'vitest'

import {
  normalizeSlaveOpenString,
  pathFromSlaveDeepLink,
  pathFromOpenDeepLink,
  resolveSlaveOpenPath
} from './hermes-open-target'

describe('normalizeSlaveOpenString', () => {
  it('accepts hash-router paths and strips a leading hash', () => {
    expect(normalizeSlaveOpenString('/index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeSlaveOpenString('#/index-network/intent/1')).toBe('/index-network/intent/1')
  })

  it('maps plugin-scoped slave:// deep links to the same path', () => {
    expect(normalizeSlaveOpenString('slave://index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeSlaveOpenString('slave://index-network/intent/1?focus=true')).toBe(
      '/index-network/intent/1?focus=true'
    )
  })

  it('maps slave://open/… deep links by stripping the open host', () => {
    expect(normalizeSlaveOpenString('slave://open/index-network/intent/1')).toBe('/index-network/intent/1')
    expect(normalizeSlaveOpenString('slave://open/settings/plugins')).toBe('/settings/plugins')
  })

  it('rejects reserved slave kinds and unsafe paths', () => {
    expect(normalizeSlaveOpenString('slave://blueprint/morning-brief')).toBeNull()
    expect(normalizeSlaveOpenString('slave://plugin/install')).toBeNull()
    expect(normalizeSlaveOpenString('https://example.com/x')).toBeNull()
    expect(normalizeSlaveOpenString('/../etc/passwd')).toBeNull()
    expect(normalizeSlaveOpenString('index-network')).toBeNull()
  })
})

describe('resolveSlaveOpenPath', () => {
  it('merges structured path + params', () => {
    expect(resolveSlaveOpenPath({ path: '/index-network/intent/1', params: { focus: 'true' } })).toBe(
      '/index-network/intent/1?focus=true'
    )
  })

  it('resolves href the same as a bare string', () => {
    expect(resolveSlaveOpenPath({ href: 'slave://index-network/intent/1' })).toBe('/index-network/intent/1')
  })
})

describe('pathFromSlaveDeepLink', () => {
  it('builds the navigate path from a plugin-scoped deep-link payload', () => {
    expect(pathFromSlaveDeepLink('index-network', 'intent/1')).toBe('/index-network/intent/1')
  })

  it('builds the navigate path from slave://open/… payloads', () => {
    expect(pathFromOpenDeepLink('index-network/intent/1')).toBe('/index-network/intent/1')
    expect(pathFromSlaveDeepLink('open', 'agent/42')).toBe('/agent/42')
  })

  it('ignores reserved kinds', () => {
    expect(pathFromSlaveDeepLink('blueprint', 'morning-brief')).toBeNull()
    expect(pathFromSlaveDeepLink('plugin', 'install')).toBeNull()
  })
})
