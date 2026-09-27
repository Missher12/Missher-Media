import { chmod, link, lstat, mkdir, mkdtemp, readFile, realpath, readdir, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { afterEach, expect, it } from 'vitest'
import { normalizePluginConfig } from '../src/config.js'
import { createSetupTool } from '../src/setup.js'

const roots: string[] = []
const csv = 'platform,creator_name,homepage_url\nxhs,测试甲,https://www.xiaohongshu.com/user/profile/abcdef0123456789abcdef01?xsec_token=DO_NOT_RETAIN\nxhs,测试乙,https://www.xiaohongshu.com/user/profile/abcdef0123456789abcdef02\nweibo,测试甲,https://weibo.com/u/12345\n'
async function fixture() {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-setup-test-')))
  roots.push(root)
  const config = normalizePluginConfig({ profilePath: join(root, 'config', 'profile.json'), runtimeHome: join(root, 'runtime'), outputRoot: join(root, 'runs') }, join(root, 'dsh'), root)
  const tool = createSetupTool(config)
  const execute = (args: unknown) => tool.execute(args as never, { signal: new AbortController().signal } as never) as Promise<Record<string, unknown>>
  const input = join(root, 'creators.csv')
  await writeFile(input, csv, { mode: 0o644 })
  return { root, config, execute, input }
}
afterEach(async () => { await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true }))) })

it('reports a blank device without creating directories, runtime or browser work', async () => {
  const f = await fixture()
  expect(await f.execute({ action: 'status' })).toMatchObject({ status: 'needs-setup', activePlatforms: '', browserStatus: 'not-checked' })
  expect(await readdir(f.root)).toEqual(['creators.csv'])
})

it('creates empty editable Excel and CSV templates without Python', async () => {
  const f = await fixture()
  const result = await f.execute({ action: 'template' })
  expect(result.status).toBe('ok')
  expect((await readFile(result.artifactPath as string)).subarray(0, 2).toString()).toBe('PK')
  expect(await readFile(result.metadataPath as string, 'utf8')).toContain('platform,creator_name,homepage_url')
  expect((await lstat(result.artifactPath as string)).mode & 0o777).toBe(0o600)
  expect(await readdir(f.root)).not.toContain('runtime')
})

it('previews immutable sanitized imports and activates only explicit rows', async () => {
  const f = await fixture()
  const result = await f.execute({ action: 'import', input_path: f.input })
  expect(result).toMatchObject({ status: 'ok', rowCount: 3, activePlatforms: '' })
  const roster = await readFile(result.metadataPath as string, 'utf8')
  const preview = await readFile(result.artifactPath as string, 'utf8')
  expect(roster + preview + JSON.stringify(result)).not.toContain('DO_NOT_RETAIN')
  expect(preview).toContain('测试甲')
  expect((await f.execute({ action: 'status' })).status).toBe('needs-setup')
  expect(await f.execute({ action: 'activate', import_id: result.importId, rows: [1] })).toMatchObject({ status: 'ok', activePlatforms: 'xhs', configuredPlatforms: 'xhs' })
  expect(JSON.parse(await readFile(f.config.profilePath, 'utf8'))).toMatchObject({ platform_uids: { xhs: 'abcdef0123456789abcdef01' }, active_platforms: ['xhs'] })
  expect(await readFile(result.metadataPath as string, 'utf8')).toBe(roster)
  expect((await lstat(f.config.profilePath)).mode & 0o777).toBe(0o600)
  expect((await lstat(dirname(result.metadataPath as string))).mode & 0o777).toBe(0o700)
  expect(await readdir(f.root)).not.toContain('runs')
})

it('backs up exact old bytes and preserves other targets and private settings', async () => {
  const f = await fixture()
  await mkdir(dirname(f.config.profilePath), { mode: 0o700 })
  const old = '{"cdp_url":"http://127.0.0.1:9555","data_root":"/private/fixture","platform_uids":{"weibo":"67890"},"custom":"PRIVATE_FIXTURE"}\n'
  await writeFile(f.config.profilePath, old, { mode: 0o600 })
  const imported = await f.execute({ action: 'import', input_path: f.input })
  const activated = await f.execute({ action: 'activate', import_id: imported.importId, rows: [2] })
  expect(activated).toMatchObject({ status: 'ok', configuredPlatforms: 'xhs,weibo', activePlatforms: 'xhs' })
  const backups = await readdir(join(dirname(f.config.profilePath), 'setup', 'backups'))
  expect(backups).toHaveLength(1)
  expect(await readFile(join(dirname(f.config.profilePath), 'setup', 'backups', backups[0]!), 'utf8')).toBe(old)
  expect(await readFile(f.config.profilePath, 'utf8')).toContain('PRIVATE_FIXTURE')
  expect(JSON.stringify(activated)).not.toContain('PRIVATE_FIXTURE')
})

it('accepts several accounts on one platform and rejects out-of-range, duplicate or absent rows', async () => {
  const f = await fixture()
  const imported = await f.execute({ action: 'import', input_path: f.input })
  for (const rows of [[0], [4], [1, 1], []]) {
    expect((await f.execute({ action: 'activate', import_id: imported.importId, rows })).status).toBe('failed')
  }
  expect((await f.execute({ action: 'status' })).status).toBe('needs-setup')
  // Rows 1 and 2 are two different Xiaohongshu accounts: that is one platform
  // with two targets, which the versioned plan expresses directly.
  const two = await f.execute({ action: 'activate', import_id: imported.importId, rows: [1, 2] })
  expect(two).toMatchObject({ status: 'ok', activePlatforms: 'xhs', rowCount: 2 })
  const saved = JSON.parse(await readFile(f.config.profilePath, 'utf8'))
  expect(saved.targets).toHaveLength(2)
  expect(saved.targets.map((target: { uid: string }) => target.uid)).toEqual(['abcdef0123456789abcdef01', 'abcdef0123456789abcdef02'])
  // A third platform can be added on top of the existing selection.
  const cross = await f.execute({ action: 'activate', import_id: imported.importId, rows: [1, 3] })
  expect(cross).toMatchObject({ status: 'ok', activePlatforms: 'xhs,weibo' })
})

it('rejects malformed imports atomically, without creating a profile or an import', async () => {
  const f = await fixture()
  await writeFile(f.input, 'platform,creator_name,homepage_url\nxhs,私密测试,https://wrong.invalid/SECRET\n')
  const result = await f.execute({ action: 'import', input_path: f.input })
  expect(result.status).toBe('failed')
  expect(JSON.stringify(result)).not.toMatch(/私密测试|SECRET|wrong.invalid/)
  expect(await readdir(f.root)).toEqual(['creators.csv'])
})

it('rejects linked uploads, linked config ancestors, unsafe file modes and traversal IDs', async () => {
  const f = await fixture()
  const linked = join(f.root, 'link.csv')
  await symlink(f.input, linked)
  expect((await f.execute({ action: 'import', input_path: linked })).status).toBe('failed')
  await rm(linked)
  await link(f.input, linked)
  expect((await f.execute({ action: 'import', input_path: linked })).status).toBe('failed')
  await rm(linked)
  await chmod(f.input, 0o666)
  expect((await f.execute({ action: 'import', input_path: f.input })).status).toBe('failed')
  await symlink(f.root, dirname(f.config.profilePath))
  expect((await f.execute({ action: 'template' })).status).toBe('failed')
  expect((await f.execute({ action: 'activate', import_id: '../../profile', rows: [1] })).status).toBe('failed')
})

it('never overwrites a malformed or nonprivate existing profile during activation', async () => {
  const f = await fixture()
  const imported = await f.execute({ action: 'import', input_path: f.input })
  for (const [content, mode] of [['bad JSON', 0o600], ['{}', 0o644]] as const) {
    await writeFile(f.config.profilePath, content, { mode })
    await chmod(f.config.profilePath, mode)
    expect((await f.execute({ action: 'activate', import_id: imported.importId, rows: [1] })).status).toBe('failed')
    expect(await readFile(f.config.profilePath, 'utf8')).toBe(content)
  }
})

it('serializes concurrent activations and retains a valid profile and lock cleanup', async () => {
  const f = await fixture()
  const imported = await f.execute({ action: 'import', input_path: f.input })
  const results = await Promise.all([1, 2].map(row => f.execute({ action: 'activate', import_id: imported.importId, rows: [row] })))
  expect(results.filter(result => result.status === 'ok')).toHaveLength(1)
  expect(results.some(result => result.summary === 'setup_busy')).toBe(true)
  expect((await f.execute({ action: 'status' })).activePlatforms).toBe('xhs')
  expect(await readdir(join(dirname(f.config.profilePath), 'setup'))).not.toContain('activate.lock')
})

it.each(['roster', 'preview'])('rejects changes to reviewed %s bytes before activation', async target => {
  const f = await fixture()
  const imported = await f.execute({ action: 'import', input_path: f.input })
  if (target === 'roster') {
    const roster = JSON.parse(await readFile(imported.metadataPath as string, 'utf8'))
    roster.creators[0] = { ...roster.creators[1], name: 'changed valid target' }
    roster.creators.splice(1, 1)
    await writeFile(imported.metadataPath as string, JSON.stringify(roster))
  } else await writeFile(imported.artifactPath as string, 'a different reviewed target')
  expect((await f.execute({ action: 'activate', import_id: imported.importId, rows: [1] })).status).toBe('failed')
  expect((await f.execute({ action: 'status' })).status).toBe('needs-setup')
})

it('keeps quoted multiline names inside one preview row', async () => {
  const f = await fixture()
  await writeFile(f.input, 'platform,creator_name,homepage_url\nxhs,"测试\n\n| 99 | 伪造 |",https://www.xiaohongshu.com/user/profile/abcdef0123456789abcdef01\n')
  const imported = await f.execute({ action: 'import', input_path: f.input })
  expect(imported.status).toBe('ok')
  const preview = await readFile(imported.artifactPath as string, 'utf8')
  expect(preview.split('\n').filter(line => line.startsWith('| '))).toHaveLength(3)
  expect(preview).not.toContain('\n| 99')
  expect(preview).toContain('测试 ↵  ↵ ')
  expect((await f.execute({ action: 'activate', import_id: imported.importId, rows: [1] })).status).toBe('ok')
})
