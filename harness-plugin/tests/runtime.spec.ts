import {
  chmod,
  mkdir,
  mkdtemp,
  realpath,
  readFile,
  utimes,
  rm,
  symlink,
  writeFile,
} from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { normalizeCollectArgs, normalizePluginConfig } from '../src/config.js'
import {
  buildControllerInvocation,
  ensureRuntime,
  loadRunEvidence,
  parseControllerSummary,
} from '../src/runtime.js'

const temporaryRoots: string[] = []

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), 'media-runtime-test-'))
  temporaryRoots.push(root)
  const dshHome = join(root, 'dsh')
  const profilePath = join(root, 'private', 'profile.json')
  const runtimeHome = join(root, 'runtime-home')
  const outputRoot = join(dshHome, 'media-missher', 'runs')
  const payloadRoot = join(root, 'payload')
  await mkdir(join(runtimeHome, 'current'), { recursive: true })
  await mkdir(join(runtimeHome, 'venv', 'bin'), { recursive: true })
  await mkdir(join(payloadRoot, 'tools'), { recursive: true })
  await mkdir(join(payloadRoot, 'media-missher', 'scripts'), { recursive: true })
  await mkdir(join(profilePath, '..'), { recursive: true })
  await writeFile(profilePath, '{"platform_uids":{}}\n', { mode: 0o600 })
  await chmod(profilePath, 0o600)
  await writeFile(join(payloadRoot, 'VERSION'), '15.2.1\n')
  await writeFile(join(payloadRoot, 'tools', 'install_media_missher.py'), '# installer\n')
  await writeFile(join(payloadRoot, 'media-missher', 'scripts', 'run_collection.py'), '# controller\n')
  const config = normalizePluginConfig({ profilePath, runtimeHome, outputRoot }, dshHome, root)
  return { root, config, payloadRoot, runtimeHome, outputRoot, profilePath }
}

async function markRuntimeReady(runtimeHome: string, version = '15.2.1') {
  const python = join(runtimeHome, 'venv', 'bin', 'python')
  await writeFile(join(runtimeHome, 'current', 'VERSION'), `${version}\n`)
  await writeFile(python, '#!/bin/sh\n', { mode: 0o700 })
  await chmod(python, 0o700)
  return python
}

async function evidenceFixture(outputRoot: string) {
  const runDirectory = join(outputRoot, 'run-20260828T000000Z-fixture')
  const engineDirectory = join(runDirectory, 'run-engine-fixture')
  await mkdir(engineDirectory, { recursive: true })
  const paths: Record<string, string> = {}
  const counts: Record<string, number> = {}
  const platforms: Record<string, string> = {}
  const diagnostics: Record<string, { kind: string; code: string }> = {}
  const evidence: string[] = []
  for (const platform of ['bilibili', 'xhs', 'douyin', 'weibo']) {
    const name = `${platform}.json`
    const path = join(engineDirectory, name)
    await writeFile(path, `${JSON.stringify([{ platform, [{ bilibili: 'dynamic_id', xhs: 'note_id', douyin: 'aweme_id', weibo: 'mblog_id' }[platform]!]: `${platform}-1`, link: 'https://example.invalid/content', title: platform }])}\n`)
    paths[platform] = name
    counts[platform] = 1
    platforms[platform] = 'complete'
    diagnostics[platform] = { kind: 'ok', code: 'ok' }
    evidence.push(path)
  }
  const manifestPath = join(engineDirectory, 'manifest.json')
  await writeFile(manifestPath, `${JSON.stringify({
    schema: 1,
    status: 'complete',
    counts,
    paths,
    platforms,
    diagnostics,
  })}\n`)
  evidence.unshift(manifestPath)
  return { runDirectory, engineDirectory, manifestPath, evidence }
}

afterEach(async () => {
  vi.restoreAllMocks()
  await Promise.all(temporaryRoots.splice(0).map(path => rm(path, { recursive: true, force: true })))
})

describe('runtime lifecycle', () => {
  it('reuses an exact executable 15.2.1 runtime without installation', async () => {
    const setup = await fixture()
    const python = await markRuntimeReady(setup.runtimeHome)
    const runner = vi.fn(() => Promise.reject(new Error('must_not_install')))

    const layout = await ensureRuntime(setup.config, {
      payloadRoot: setup.payloadRoot,
      platform: 'darwin',
      processRunner: runner,
    })

    expect(layout.python).toBe(python)
    expect(runner).not.toHaveBeenCalled()
  })

  it('reuses the normal executable symlink created by a Python venv', async () => {
    const setup = await fixture()
    const target = join(setup.runtimeHome, 'venv', 'bin', 'python3.11')
    const python = join(setup.runtimeHome, 'venv', 'bin', 'python')
    await writeFile(join(setup.runtimeHome, 'current', 'VERSION'), '15.2.1\n')
    await writeFile(target, '#!/bin/sh\n', { mode: 0o700 })
    await chmod(target, 0o700)
    await symlink('python3.11', python)
    const runner = vi.fn(() => Promise.reject(new Error('must_not_install')))

    const layout = await ensureRuntime(setup.config, {
      payloadRoot: setup.payloadRoot,
      platform: 'darwin',
      processRunner: runner,
    })

    expect(layout.python).toBe(python)
    expect(runner).not.toHaveBeenCalled()
  })

  it('atomically provisions a stale runtime from the embedded payload', async () => {
    const setup = await fixture()
    await markRuntimeReady(setup.runtimeHome, '15.0.0')
    const runner = vi.fn(async (_executable: string, args: readonly string[]) => {
      expect(args).toEqual([
        join(setup.payloadRoot, 'tools', 'install_media_missher.py'),
        '--source', setup.payloadRoot,
        '--home', setup.runtimeHome,
        '--runtime-only',
      ])
      await markRuntimeReady(setup.runtimeHome)
      return { code: 0, signal: null, stdout: '{}\n', stderr: '' }
    })

    await ensureRuntime(setup.config, {
      payloadRoot: setup.payloadRoot,
      platform: 'darwin',
      installPython: '/usr/bin/python3',
      processRunner: runner,
    })

    expect(runner).toHaveBeenCalledOnce()
    expect(runner.mock.calls[0]?.[0]).toBe('/usr/bin/python3')
  })

  it('fails unsupported platforms before mutation', async () => {
    const setup = await fixture()
    const runner = vi.fn()
    await expect(ensureRuntime(setup.config, {
      payloadRoot: setup.payloadRoot,
      platform: 'win32',
      processRunner: runner,
    })).rejects.toThrow('platform_unsupported')
    expect(runner).not.toHaveBeenCalled()
  })
})

describe('controller invocation', () => {
  it('builds the zero-argument four-platform by ten command without UIDs', async () => {
    const setup = await fixture()
    const python = await markRuntimeReady(setup.runtimeHome)
    const args = normalizeCollectArgs({}, setup.config)
    const invocation = buildControllerInvocation(
      setup.config,
      args,
      { python, payloadRoot: setup.payloadRoot },
    )

    expect(invocation.executable).toBe(python)
    expect(invocation.args).toEqual([
      join(setup.payloadRoot, 'media-missher', 'scripts', 'run_collection.py'),
      '--profile', setup.profilePath,
      '--data-root', setup.outputRoot,
      '--platform', 'bilibili,xhs,douyin,weibo',
      '--count', '10',
      '--xhs-comments', '0',
      '--platform-timeout', '300',
      '--execution-timeout', '1260',
      '--allow-navigation',
      '--no-feishu',
      '--json-summary',
    ])
    expect(JSON.stringify(invocation)).not.toContain('platform_uids')
    expect(invocation.env).toMatchObject({
      MEDIA_MISSHER_HOME: setup.runtimeHome,
      PYTHONDONTWRITEBYTECODE: '1',
    })
  })

  it('parses one bounded controller summary', () => {
    const manifestPath = '/private/run/engine/manifest.json'
    expect(parseControllerSummary(JSON.stringify({
      status: 'success',
      run_dir: '/private/run',
      evidence: ['/private/run/engine/bilibili.json'],
      validation: {
        counts: { bilibili: 10 },
        diagnostics: [{ path: manifestPath, status: 'complete', platforms: {} }],
      },
    }))).toMatchObject({
      status: 'success',
      runDirectory: '/private/run',
      manifestPath,
    })
    expect(() => parseControllerSummary('{}')).toThrow('controller_summary_invalid')
  })
})

describe('fresh run evidence', () => {
  it('loads only manifest-declared records from the controller run', async () => {
    const setup = await fixture()
    const evidence = await evidenceFixture(setup.outputRoot)
    const result = await loadRunEvidence({
      status: 'success',
      runDirectory: evidence.runDirectory,
      evidence: evidence.evidence,
      manifestPath: evidence.manifestPath,
    }, setup.config)

    expect(result.manifestPath).toBe(await realpath(evidence.manifestPath))
    expect(result.totalCollected).toBe(4)
    expect(result.records.bilibili[0]).toMatchObject({ dynamic_id: 'bilibili-1' })
    expect(result.diagnostics.weibo).toEqual({ kind: 'ok', code: 'ok' })
  })

  it('rejects evidence outside the controller run directory', async () => {
    const setup = await fixture()
    const evidence = await evidenceFixture(setup.outputRoot)
    const outside = join(setup.root, 'manifest.json')
    await writeFile(outside, '{}\n')

    await expect(loadRunEvidence({
      status: 'success',
      runDirectory: evidence.runDirectory,
      evidence: [outside],
      manifestPath: evidence.manifestPath,
    }, setup.config)).rejects.toThrow('evidence_path_escape')
  })

  it('rejects symlinked evidence and manifest count mismatches', async () => {
    const setup = await fixture()
    const evidence = await evidenceFixture(setup.outputRoot)
    const link = join(evidence.engineDirectory, 'linked-manifest.json')
    await symlink(evidence.manifestPath, link)
    await expect(loadRunEvidence({
      status: 'success',
      runDirectory: evidence.runDirectory,
      evidence: [link],
      manifestPath: link,
    }, setup.config)).rejects.toThrow('evidence_symlink_forbidden')

    const manifest = JSON.parse(await import('node:fs/promises').then(fs => fs.readFile(evidence.manifestPath, 'utf8')))
    manifest.counts.bilibili = 2
    await writeFile(evidence.manifestPath, JSON.stringify(manifest))
    await expect(loadRunEvidence({
      status: 'success',
      runDirectory: evidence.runDirectory,
      evidence: evidence.evidence,
      manifestPath: evidence.manifestPath,
    }, setup.config)).rejects.toThrow('manifest_count_mismatch')
  })
  it('exports first-seen native IDs only even when the source manifest counts duplicate rows', async () => {
    const setup = await fixture()
    const evidence = await evidenceFixture(setup.outputRoot)
    const path = join(evidence.engineDirectory, 'bilibili.json')
    const records = JSON.parse(await readFile(path, 'utf8'))
    await writeFile(path, JSON.stringify([...records, { ...records[0], title: 'duplicate' }]))
    const manifest = JSON.parse(await readFile(evidence.manifestPath, 'utf8'))
    manifest.counts.bilibili = 2
    await writeFile(evidence.manifestPath, JSON.stringify(manifest))
    const result = await loadRunEvidence({ status: 'success', runDirectory: evidence.runDirectory,
      evidence: evidence.evidence, manifestPath: evidence.manifestPath }, setup.config)
    expect(result.records.bilibili).toHaveLength(1)
    expect(result.records.bilibili[0]!.title).toBe('bilibili')
    expect(result.totalCollected).toBe(4)
  })

  it('rejects stale evidence before export using this invocation start time', async () => {
    const setup = await fixture()
    const evidence = await evidenceFixture(setup.outputRoot)
    await chmod(evidence.runDirectory, 0o700)
    for (const path of evidence.evidence) await chmod(path, 0o600)
    await utimes(evidence.manifestPath, new Date(0), new Date(0))
    await expect(loadRunEvidence({ status: 'success', runDirectory: evidence.runDirectory,
      evidence: evidence.evidence, manifestPath: evidence.manifestPath }, setup.config,
      { startedAtMs: Date.now() - 1000 })).rejects.toThrow('evidence_stale')
  })

  it('rejects free-form private diagnostic text before projection', async () => {
    const setup = await fixture()
    const evidence = await evidenceFixture(setup.outputRoot)
    const manifest = JSON.parse(await readFile(evidence.manifestPath, 'utf8'))
    manifest.diagnostics.bilibili = { kind: 'internal', code: 'private fixture text' }
    await writeFile(evidence.manifestPath, JSON.stringify(manifest))
    await expect(loadRunEvidence({ status: 'failed', runDirectory: evidence.runDirectory,
      evidence: evidence.evidence, manifestPath: evidence.manifestPath }, setup.config))
      .rejects.toThrow('manifest_diagnostic_invalid')
  })

})
