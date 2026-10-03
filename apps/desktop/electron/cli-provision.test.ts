import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { test, type TestContext } from 'vitest'

import { provisionCliLinks, removeBundleCliLinks } from './cli-provision'

function fixture(): { root: string; binDir: string; source: string } {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'slave-cli-links-'))
  const binDir = path.join(root, 'bin')
  const source = path.join(root, 'new', 'agent-payload', 'bin', 'slave')

  fs.mkdirSync(path.dirname(source), { recursive: true })
  fs.mkdirSync(binDir)
  fs.writeFileSync(source, 'payload command\n')

  return { root, binDir, source }
}

test.runIf(process.platform !== 'win32')(
  'retiring a bundle removes only its direct CLI links, including dangling ones',
  (): void => {
    const { root, binDir, source }: ReturnType<typeof fixture> = fixture()
    const payload: string = path.dirname(path.dirname(source))
    const target: string = path.join(binDir, 'slave')

    try {
      provisionCliLinks({ slave: source }, binDir, (): void => {})
      fs.symlinkSync(path.join(root, 'other/agent-payload/bin/other'), path.join(binDir, 'other'))
      fs.symlinkSync(source, path.join(binDir, 'personal-alias'))
      fs.writeFileSync(path.join(binDir, 'custom'), 'keep')
      fs.rmSync(source)
      removeBundleCliLinks(payload, binDir)
      assert.equal(fs.lstatSync(target, { throwIfNoEntry: false }), undefined)
      assert.deepEqual(fs.readdirSync(binDir).sort(), ['custom', 'other', 'personal-alias'])
      removeBundleCliLinks(payload, binDir)
      assert.equal(fs.readFileSync(path.join(binDir, 'custom'), 'utf8'), 'keep')
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  }
)

test('repairs owned dangling CLI links without changing foreign or live entries', context => {
  const { root, binDir, source } = fixture()
  const messages: string[] = []
  const target = path.join(binDir, 'slave')

  try {
    const oldSource = path.join(root, 'old', 'agent-payload', 'bin', 'slave')

    try {
      fs.symlinkSync(oldSource, target)
    } catch (error) {
      if (process.platform === 'win32' && (error as NodeJS.ErrnoException).code === 'EPERM') {
        context.skip('Windows symlinks require Developer Mode or elevation')
      }

      throw error
    }

    provisionCliLinks({ slave: source }, binDir, message => messages.push(message))
    assert.equal(fs.readlinkSync(target), source)
    assert.equal(fs.readFileSync(source, 'utf8'), 'payload command\n')
    assert.deepEqual(fs.readdirSync(binDir), ['slave'])

    const foreign = path.join(root, 'removed-other-tool', 'slave')
    const otherName = path.join(root, 'old', 'agent-payload', 'bin', 'other')

    for (const destination of [source, foreign, otherName, 'agent-payload/bin/hermes']) {
      fs.unlinkSync(target)
      fs.symlinkSync(destination, target)
      const original = fs.readlinkSync(target)

      provisionCliLinks({ slave: source }, binDir, message => messages.push(message))
      assert.equal(fs.readlinkSync(target), original)
      assert.deepEqual(fs.readdirSync(binDir), ['slave'])
    }

    fs.unlinkSync(target)
    fs.writeFileSync(target, 'user command\n')
    provisionCliLinks({ slave: source }, binDir, message => messages.push(message))
    assert.equal(fs.readFileSync(target, 'utf8'), 'user command\n')
    fs.unlinkSync(target)
    provisionCliLinks({ slave: source }, binDir, message => messages.push(message))
    assert.equal(fs.readlinkSync(target), source)
    assert.equal(messages.filter(message => message.includes('linked 1')).length, 2)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('qualified CLI paths expose their filenames, not shared canonical command keys', (context: TestContext): void => {
  const { root, binDir, source }: ReturnType<typeof fixture> = fixture()

  try {
    const plain: string = path.join(binDir, 'slave')
    fs.writeFileSync(plain, 'stable command')

    try {
      fs.symlinkSync(source, path.join(binDir, 'probe'))
      fs.unlinkSync(path.join(binDir, 'probe'))
    } catch (error) {
      if (process.platform === 'win32' && (error as NodeJS.ErrnoException).code === 'EPERM') {
        context.skip('Windows symlinks require Developer Mode or elevation')
      }

      throw error
    }

    for (const name of ['slave-canary', 'slave-abcdef1', 'slave-1234567']) {
      const cli: string = path.join(path.dirname(source), name)
      const acp: string = `${cli}-acp`
      fs.writeFileSync(cli, name)
      fs.writeFileSync(acp, `${name}-acp`)
      provisionCliLinks({ slave: cli, 'slave-acp': acp }, binDir, (): void => {})
      assert.equal(fs.readlinkSync(path.join(binDir, name)), cli)
      assert.equal(fs.readlinkSync(path.join(binDir, `${name}-acp`)), acp)
    }

    assert.equal(fs.readFileSync(plain, 'utf8'), 'stable command')
    assert.equal(fs.existsSync(path.join(binDir, 'slave-acp')), false)
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

test('a failed link swap preserves its source and target, then provisions later commands', context => {
  const { root, binDir, source } = fixture()
  const target = path.join(binDir, 'slave')
  const oldSource = path.join(root, 'old', 'agent-payload', 'bin', 'slave')
  const acpSource = path.join(path.dirname(source), 'slave-acp')
  const messages: string[] = []
  let swaps = 0

  try {
    try {
      fs.symlinkSync(oldSource, target)
    } catch (error) {
      if (process.platform === 'win32' && (error as NodeJS.ErrnoException).code === 'EPERM') {
        context.skip('Windows symlinks require Developer Mode or elevation')
      }

      throw error
    }

    fs.writeFileSync(acpSource, 'ACP command\n')
    provisionCliLinks({ slave: source, 'slave-acp': acpSource }, binDir, message => messages.push(message), {
      ...fs,
      renameSync: (from, to) => {
        swaps += 1
        fs.unlinkSync(from)
        fs.renameSync(from, to)
      }
    })

    assert.equal(swaps, 1)
    assert.equal(fs.readlinkSync(target), oldSource)
    assert.equal(fs.readFileSync(source, 'utf8'), 'payload command\n')
    assert.equal(fs.readlinkSync(path.join(binDir, 'slave-acp')), acpSource)
    assert.deepEqual(fs.readdirSync(binDir).sort(), ['slave', 'slave-acp'])
    assert.ok(messages.some(message => message.includes('slave') && message.includes('ENOENT')))
    assert.ok(messages.some(message => message.includes('linked 1')))
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})
