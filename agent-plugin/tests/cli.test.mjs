import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import { copyFile, chmod, lstat, mkdir, mkdtemp, readFile, readdir, realpath, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { afterEach, test } from 'node:test'
import { TARGET_ERROR_CODES } from '../src/targets.mjs'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const entry = join(packageRoot, 'bin', 'media-missher.mjs')
const roots = []
const importId = `import-${'a'.repeat(32)}-${'b'.repeat(64)}`
const fakeCore = `
import { writeFile } from 'node:fs/promises'
export function normalizePluginConfig(input, namespace, home) { return { ...input, namespace, home } }
function tool(kind, config, dependencies = {}) { return { async execute(args, { signal }) {
  if (process.env.TEST_PROGRESS) {
    dependencies.onProgress?.({ schema: 1, phase: 'engine', state: 'started', elapsed_ms: 0 })
    setTimeout(() => dependencies.onProgress?.({ schema: 1, phase: 'engine', state: 'completed', elapsed_ms: 1, duration_ms: 1 }), 20)
  }
  if (process.env.TEST_READY) {
    process.stderr.write('READY\\n')
    await new Promise(resolve => {
      const timer = setInterval(() => {}, 1000)
      signal.addEventListener('abort', () => { clearInterval(timer); resolve() }, { once: true })
    })
    await new Promise(resolve => setTimeout(resolve, 50))
    await writeFile(process.env.TEST_READY, 'cleanup-complete')
    dependencies.onProgress?.({ schema: 1, phase: 'engine', state: 'cancelled', elapsed_ms: 2, duration_ms: 2 })
  }
  if (process.env.TEST_THROW) throw new Error(process.env.TEST_THROW)
  return { status: process.env.TEST_STATUS || 'ok', kind, args, config, ...(process.env.TEST_BROWSER_STATUS ? { browserStatus: process.env.TEST_BROWSER_STATUS, activePlatforms: 'xhs' } : {}), ...(process.env.TEST_SETUP_FAILURE ? { summary: process.env.TEST_SETUP_FAILURE, activePlatforms: '', browserStatus: 'not-checked' } : {}) }
} } }
export const createSetupTool = config => tool('setup', config)
export const createMediaTool = (config, dependencies) => tool('collect', config, dependencies)
export const createRunsTool = config => tool('runs', config)
`

async function fixture(fake = false) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-agent-cli-')))
  roots.push(root)
  const home = join(root, 'home')
  await mkdir(home, { mode: 0o700 })
  const env = { ...process.env, HOME: home, DSH_HOME: join(root, 'must-not-use-dsh') }
  for (const key of Object.keys(env)) if (/^(?:MEDIA_MISSHER_|CODEX_HOME$|TEST_)/u.test(key)) delete env[key]
  let cli = entry
  if (fake) {
    const packed = join(root, 'package')
    for (const dir of ['bin', 'src', 'skill', 'lib']) await mkdir(join(packed, dir), { recursive: true })
    for (const file of ['bin/media-missher.mjs', 'src/skills.mjs', 'src/platform.mjs', 'src/targets.mjs', 'src/capabilities.mjs', 'skill/SKILL.md']) await copyFile(join(packageRoot, file), join(packed, file))
    await writeFile(join(packed, 'package.json'), JSON.stringify({ name: '@missher/media-missher', version: '17.0.0', type: 'module' }))
    await writeFile(join(packed, 'lib/index.js'), fakeCore)
    cli = join(packed, 'bin/media-missher.mjs')
  }
  const run = (args, extraEnv = {}) => {
    const child = spawnSync(process.execPath, [cli, ...args], { env: { ...env, ...extraEnv }, encoding: 'utf8', timeout: 15000 })
    let value
    try { value = JSON.parse(child.stdout) } catch {}
    return { ...child, value }
  }
  return { root, home, env, cli, run }
}

async function syntheticWslMount(f, mountedPath) {
  const sourcePlatform = pathToFileURL(join(packageRoot, 'src/platform.mjs')).href
  const mountinfo = `24 1 8:1 / / rw - ext4 /dev/sda rw\n25 24 0:31 / /home/fixture/${mountedPath} rw - 9p C: rw\n`
  // Exercise the shared mount check with an isolated HOME, without creating real /home paths.
  await writeFile(join(dirname(dirname(f.cli)), 'src/platform.mjs'), `
    import { checkStorage as sharedCheck, StorageError } from ${JSON.stringify(sourcePlatform)}
    import { relative } from 'node:path'
    export { StorageError }
    export const wslEnvironment = () => true
    export const checkStorage = (home, paths) => sharedCheck('/home/fixture', paths.map(path => '/home/fixture/' + relative(home, path)), {
      platform: 'linux', uid: 1000, kernel: 'microsoft-WSL2', mountinfo: ${JSON.stringify(mountinfo)}
    })
  `)
}

afterEach(async () => { await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true }))) })

test('help, version and agent discovery need no runtime and leave an empty HOME unchanged', async () => {
  const f = await fixture()
  for (const args of [['--help'], ['--version'], ['install-skill', '--list']]) {
    const result = f.run(args)
    assert.equal(result.status, 0, result.stderr)
    assert.equal(result.value.status, 'ok')
  }
  assert.equal(f.run(['--version']).value.runtimeRequired, '17.0.0')
  assert.deepEqual(f.run(['install-skill', '--list']).value.agents.map(agent => agent.name), ['codex', 'claude', 'cursor', 'openclaw', 'hermes'])
  assert.deepEqual(await readdir(f.home), [])
})

test('the package bin works when invoked through an npm-style executable symlink', async () => {
  const f = await fixture()
  const linked = join(f.root, 'media-missher')
  await symlink(entry, linked)
  const result = spawnSync(process.execPath, [linked, '--version'], { env: f.env, encoding: 'utf8', timeout: 15000 })
  assert.equal(result.status, 0, result.stderr)
  assert.ok(result.stdout.trim(), 'the bin symlink must execute the CLI')
  assert.equal(JSON.parse(result.stdout).name, '@missher/media-missher')
})

test('strict command validation rejects extraneous, duplicate and malformed options before creating files', async () => {
  const f = await fixture()
  const invalid = [
    ['doctor', '--allow-navigation'], ['setup', 'status', '--file', '/private/SECRET'],
    ['setup', 'browser-open'], ['setup', 'import', '--file', 'relative.csv'],
    ['setup', 'activate', '--import-id', importId, '--rows', '1,1'],
    ['collect', '--count', '1.5'], ['collect', '--count', '2', '--count', '3'],
    ['collect', '--platforms', 'xhs,xhs'], ['collect', '--platforms', 'xhs', '--count', '11'],
    ['collect', '--platforms', 'weibo', '--xhs-comments', '1'],
    ['runs', 'list', '--run-id', 'run-one'], ['runs', 'export', '--run-id', '../SECRET'],
    ['runs', 'compare', '--before', 'run-one'], ['install-skill', '--list', '--agent', 'codex'],
    ['install-skill', '--agent', 'codex', '--skill-root', join(f.home, 'skills')],
    ['install-skill', '--agent', 'unknown'], ['--help', '--SECRET'], ['--version', 'extra'],
  ]
  for (const args of invalid) {
    const result = f.run(args)
    assert.equal(result.status, 2, `${args.join(' ')}: ${result.stdout} ${result.stderr}`)
    assert.equal(result.value.error, 'cli_arguments_invalid')
    assert.doesNotMatch(result.stdout + result.stderr, /SECRET|Error:| at /u)
  }
  assert.deepEqual(await readdir(f.home), [])
})

test('doctor reports a blank device offline and collection fails before runtime or output creation', async () => {
  const f = await fixture()
  const result = f.run(['doctor'])
  assert.equal(result.status, 3, result.stderr)
  assert.equal(result.value.status, 'needs-setup')
  assert.equal(result.value.runtime.status, 'missing')
  assert.equal(result.value.browser.status, 'not-checked')
  assert.equal(result.value.browser.loginStatus, 'not-checked')
  assert.ok(result.value.nextSteps.some(step => step.includes('setup template')))
  assert.equal(result.value.paths.outputRoot, join(f.home, '.local/share/media-missher-agent/runs'))
  const collection = f.run(['collect'])
  assert.equal(collection.status, 3, collection.stderr)
  assert.equal(collection.value.status, 'needs-input')
  assert.deepEqual(collection.value.missingFields, ['platforms', 'targets'])
  assert.ok(collection.value.nextSteps.length)
  assert.deepEqual(await readdir(f.home), [])
})

test('doctor bounds existing VERSION reads, rejects links and never exposes malformed content', async () => {
  const f = await fixture()
  const runtime = join(f.home, 'runtime')
  await mkdir(join(runtime, 'current'), { recursive: true, mode: 0o700 })
  const version = join(runtime, 'current/VERSION')
  await writeFile(version, '14.0.0\n', { mode: 0o600 })
  let result = f.run(['doctor', '--runtime-home', runtime])
  assert.equal(result.value.runtime.currentVersion, '14.0.0')
  assert.equal(result.value.runtime.status, 'version-mismatch')
  await writeFile(version, 'PRIVATE_SECRET'.repeat(100))
  result = f.run(['doctor', '--runtime-home', runtime])
  assert.equal(result.value.runtime.status, 'invalid')
  assert.doesNotMatch(result.stdout + result.stderr, /PRIVATE_SECRET/u)
  await rm(version)
  await symlink(join(f.home, 'not-present'), version)
  assert.equal(f.run(['doctor', '--runtime-home', runtime]).value.runtime.status, 'invalid')
})

test('the actual CLI imports a roster, preserves the preview and activates selected rows without a runtime', async () => {
  const f = await fixture()
  const template = f.run(['setup', 'template'])
  assert.equal(template.status, 0, template.stderr)
  assert.equal((await readFile(template.value.artifactPath)).subarray(0, 2).toString(), 'PK')
  const input = join(f.home, 'creators.csv')
  await writeFile(input, 'platform,creator_name,homepage_url\nxhs,Fixture,https://www.xiaohongshu.com/user/profile/abcdef0123456789abcdef01\n', { mode: 0o600 })
  const imported = f.run(['setup', 'import', '--file', input])
  assert.equal(imported.status, 0, imported.stderr)
  const preview = await readFile(imported.value.artifactPath)
  assert.equal(f.run(['setup', 'status']).value.status, 'needs-setup')
  const active = f.run(['setup', 'activate', '--import-id', imported.value.importId, '--rows', '1'])
  assert.equal(active.status, 0, active.stderr)
  assert.equal(active.value.activePlatforms, 'xhs')
  assert.deepEqual(await readFile(imported.value.artifactPath), preview)
  assert.equal((await lstat(join(f.home, '.config/media-missher/profile.json'))).mode & 0o777, 0o600)
  assert.equal(f.run(['runs', 'progress']).status, 0)
  assert.deepEqual((await readdir(f.home)).sort(), ['.config', 'creators.csv'])
})

test('commands use shared factories and independent paths with explicit flags overriding existing environment conventions', async () => {
  const f = await fixture(true)
  const runtime = join(f.home, 'runtime')
  const output = join(f.home, 'output')
  const profile = join(f.home, 'explicit.json')
  const result = f.run(['collect', '--platforms', 'weibo,xhs', '--count', '2', '--xhs-comments', '3', '--allow-navigation', '--resume-run', 'run-fixture', '--profile', profile, '--output-root', output], { MEDIA_MISSHER_HOME: runtime, MEDIA_MISSHER_PROFILE_CONFIG: join(f.home, 'env.json') })
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(result.value.args, { platforms: 'xhs,weibo', count: 2, xhs_comments: 3, allow_navigation: true, resume_run: 'run-fixture' })
  assert.equal(result.value.config.runtimeHome, runtime)
  assert.equal(result.value.config.profilePath, profile)
  assert.equal(result.value.config.outputRoot, output)
  assert.doesNotMatch(JSON.stringify(result.value.config), /must-not-use-dsh/u)
  assert.deepEqual(f.run(['runs', 'export', '--run-id', 'run-one', '--format', 'csv']).value.args, { action: 'export', run_id: 'run-one', format: 'csv' })
  assert.deepEqual(f.run(['runs', 'compare', '--before', 'run-one', '--after', 'run-two']).value.args, { action: 'compare', before: 'run-one', after: 'run-two' })
})

test('failure statuses stay nonzero and raw exceptions never reach JSON or stderr', async () => {
  const f = await fixture(true)
  for (const status of ['partial', 'failed', 'preflight-failed', 'risk-stopped']) assert.notEqual(f.run(['collect'], { TEST_STATUS: status }).status, 0)
  const failure = f.run(['collect'], { TEST_THROW: 'cookie=PRIVATE_SECRET\n/path/private' })
  assert.equal(failure.value.error, 'operation_failed')
  assert.doesNotMatch(failure.stdout + failure.stderr, /PRIVATE_SECRET|\/path\/private|Error:| at /u)
})

test('fixed collection progress reaches stderr while stdout stays one JSON result, with no events after completion', async () => {
  const f = await fixture(true)
  const result = f.run(['collect'], { TEST_PROGRESS: '1' })
  assert.equal(result.status, 0)
  assert.equal(result.value.kind, 'collect')
  assert.ok(result.stderr.trim(), 'collection emits the fixed progress event on stderr')
  assert.deepEqual(result.stderr.trim().split('\n').map(line => JSON.parse(line.replace(/^media-missher-progress /u, ''))), [{ schema: 1, phase: 'engine', state: 'started', elapsed_ms: 0 }])
  assert.doesNotMatch(result.stdout, /media-missher-progress/u)
})

test('browser preparation next steps preserve already selected creators', async () => {
  const f = await fixture(true)
  for (const status of ['missing-chrome', 'starting', 'busy', 'not-running']) {
    const result = f.run(['setup', 'browser-check'], { TEST_STATUS: 'needs-setup', TEST_BROWSER_STATUS: status })
    assert.equal(result.status, 3)
    assert.doesNotMatch(result.value.nextSteps.join(' '), /setup template|setup import/u)
    assert.ok(result.value.nextSteps.length)
  }
})

test('failed graphical-session, root and platform browser preparation returns actionable guidance without requiring active platform fields', async () => {
  const f = await fixture(true)
  for (const [code, expected] of [
    ['setup_browser_graphical_session_required', /graphical|WSLg/u],
    ['setup_browser_root_unsupported', /non-root|normal Linux user/u],
    ['setup_browser_platform_unsupported', /WSL2/u],
  ]) {
    const result = f.run(['setup', 'browser-open', '--confirm-open'], { TEST_STATUS: 'failed', TEST_SETUP_FAILURE: code })
    assert.equal(result.status, 1)
    assert.equal(result.value.summary, code)
    assert.ok(Array.isArray(result.value.nextSteps), `${code} must give its specific next step`)
    assert.match(result.value.nextSteps.join(' '), expected)
    assert.doesNotMatch(result.value.nextSteps.join(' '), /setup template|setup import/u)
  }
  assert.deepEqual(await readdir(f.home), [])
})

for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143]]) test(`${signal} waits for shared operation cleanup and retains its exit code`, async () => {
  const f = await fixture(true)
  const cleanup = join(f.home, 'cleanup')
  const child = spawn(process.execPath, [f.cli, 'collect'], { env: { ...f.env, TEST_READY: cleanup }, stdio: ['ignore', 'pipe', 'pipe'] })
  let output = ''
  let errors = ''
  child.stdout.on('data', bytes => { output += bytes })
  child.stderr.on('data', bytes => { errors += bytes })
  const closed = new Promise((resolve, reject) => { child.once('close', (exit, term) => resolve({ exit, term })); child.once('error', reject) })
  await new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { child.kill('SIGKILL'); reject(new Error('fixture not ready')) }, 5000)
    child.stderr.on('data', bytes => { if (bytes.toString().includes('READY')) { clearTimeout(timeout); resolve() } })
  })
  child.kill(signal)
  const completed = await closed
  assert.deepEqual(completed, { exit: code, term: null })
  assert.equal(await readFile(cleanup, 'utf8'), 'cleanup-complete')
  assert.equal(JSON.parse(output).error, 'operation_cancelled')
  assert.doesNotMatch(errors, /"state":"cancelled"/u)
})

test('explicit skill installation is idempotent and does not modify other Agent roots', async () => {
  const f = await fixture()
  const first = f.run(['install-skill', '--agent', 'claude'])
  assert.equal(first.status, 0, first.stderr)
  assert.equal(first.value.action, 'installed')
  const installed = join(f.home, '.claude/skills/media-missher')
  const bytes = await readFile(join(installed, 'SKILL.md'))
  assert.ok(bytes.toString().includes(await realpath(entry)))
  assert.doesNotMatch(bytes.toString(), /\{\{MEDIA_MISSHER_COMMAND\}\}/u)
  assert.equal((await lstat(installed)).mode & 0o777, 0o700)
  assert.equal((await lstat(join(installed, 'SKILL.md'))).mode & 0o777, 0o600)
  const second = f.run(['install-skill', '--agent', 'claude'])
  assert.equal(second.status, 0, second.stderr)
  assert.equal(second.value.action, 'unchanged')
  assert.deepEqual(await readFile(join(installed, 'SKILL.md')), bytes)
  assert.deepEqual(await readdir(f.home), ['.claude'])
})

test('skill installation preserves unrelated, edited and linked destinations', async () => {
  const f = await fixture()
  const root = join(f.home, 'skills')
  const target = join(root, 'media-missher')
  await mkdir(target, { recursive: true, mode: 0o700 })
  await writeFile(join(target, 'SKILL.md'), 'old unrelated skill', { mode: 0o600 })
  let result = f.run(['install-skill', '--skill-root', root])
  assert.equal(result.value.error, 'skill_conflict')
  assert.equal(result.value.path, target)
  assert.equal(await readFile(join(target, 'SKILL.md'), 'utf8'), 'old unrelated skill')
  await rm(target, { recursive: true })
  assert.equal(f.run(['install-skill', '--skill-root', root]).status, 0)
  await writeFile(join(target, 'SKILL.md'), 'user edit')
  result = f.run(['install-skill', '--skill-root', root])
  assert.equal(result.value.error, 'skill_conflict')
  assert.equal(await readFile(join(target, 'SKILL.md'), 'utf8'), 'user edit')
  const linked = join(f.home, 'linked')
  await symlink(root, linked)
  assert.equal(f.run(['install-skill', '--skill-root', linked]).value.error, 'skill_path_unsafe')
  assert.equal(await readFile(join(target, 'SKILL.md'), 'utf8'), 'user edit')
})

test('owned skill upgrade backs up the exact previous skill and ownership marker', async () => {
  const f = await fixture(true)
  const root = join(f.home, 'skills')
  const installed = join(root, 'media-missher')
  assert.equal(f.run(['install-skill', '--skill-root', root]).status, 0)
  const before = new Map(await Promise.all((await readdir(installed)).map(async name => [name, await readFile(join(installed, name))])))
  const template = join(dirname(dirname(f.cli)), 'skill/SKILL.md')
  await writeFile(template, `${await readFile(template, 'utf8')}\nUpdated fixture guidance.\n`)
  const result = f.run(['install-skill', '--skill-root', root])
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.value.action, 'updated')
  assert.ok(result.value.backupPath.startsWith(join(f.home, '.local/share/media-missher-agent/skill-backups/')))
  for (const [name, bytes] of before) assert.deepEqual(await readFile(join(result.value.backupPath, name)), bytes)
  assert.equal((await lstat(result.value.backupPath)).mode & 0o777, 0o700)
  assert.match(await readFile(join(installed, 'SKILL.md'), 'utf8'), /Updated fixture guidance/u)
  assert.deepEqual((await readdir(root)).sort(), ['media-missher'])
})

test('a failed upgrade backup preserves the installed bytes and removes its lock and pending skill', async () => {
  const f = await fixture(true)
  const root = join(f.home, 'skills')
  const installed = join(root, 'media-missher')
  assert.equal(f.run(['install-skill', '--skill-root', root]).status, 0)
  const before = new Map(await Promise.all((await readdir(installed)).map(async name => [name, await readFile(join(installed, name))])))
  const template = join(dirname(dirname(f.cli)), 'skill/SKILL.md')
  await writeFile(template, `${await readFile(template, 'utf8')}\nFixture upgrade.\n`)
  const backupRoot = join(f.home, '.local/share/media-missher-agent/skill-backups')
  await mkdir(backupRoot, { recursive: true, mode: 0o700 })
  await chmod(backupRoot, 0o777)
  const result = f.run(['install-skill', '--skill-root', root])
  assert.equal(result.status, 1)
  assert.equal(result.value.error, 'skill_path_unsafe')
  for (const [name, bytes] of before) assert.deepEqual(await readFile(join(installed, name)), bytes)
  assert.deepEqual(await readdir(root), ['media-missher'])
  assert.deepEqual(await readdir(backupRoot), [])
  assert.equal((await lstat(backupRoot)).mode & 0o777, 0o777)
})

test('native Windows reports the WSL prerequisite without loading or creating a runtime', async () => {
  const f = await fixture()
  const { runCli } = await import(pathToFileURL(entry))
  const result = await runCli(['doctor'], { env: f.env, platform: 'win32' })
  assert.equal(result.exitCode, 1)
  assert.equal(result.value.error, 'native_windows_unsupported')
  assert.ok(result.value.nextSteps.some(step => step.includes('WSL')))
  assert.deepEqual(await readdir(f.home), [])
})

test('WSL rejects root, mounted Windows HOME and paths outside the Linux user HOME before operations', async () => {
  const f = await fixture()
  const { runCli } = await import(pathToFileURL(entry))
  const wsl = { env: { ...f.env, HOME: '/home/media-fixture', WSL_DISTRO_NAME: 'Fixture' }, platform: 'linux', release: '5.15.0-microsoft-standard-WSL2', uid: 1000, mountinfo: '24 1 8:1 / / rw - ext4 /dev/sda rw\n' }
  for (const [options, error] of [[{ ...wsl, uid: 0 }, 'platform_linux_user_required'], [{ ...wsl, env: { ...wsl.env, HOME: '/mnt/c/Users/Fixture' } }, 'platform_wsl_home_required']]) {
    const result = await runCli(['doctor'], options)
    assert.equal(result.exitCode, 1)
    assert.equal(result.value.error, error)
  }
  for (const args of [
    ['doctor', '--profile', '/mnt/c/Users/Fixture/profile.json'],
    ['doctor', '--runtime-home', '/mnt/c/runtime'],
    ['doctor', '--output-root', '/home/other/runs'],
    ['install-skill', '--skill-root', join(f.home, 'skills')],
  ]) {
    const result = await runCli(args, wsl)
    assert.equal(result.exitCode, 1)
    assert.equal(result.value.error, 'platform_wsl_home_required')
  }
  assert.deepEqual(await readdir(f.home), [])
})

test('WSL doctor rejects Windows mounts at derived browser, setup, runtime, output and shared-state locations', async () => {
  const f = await fixture(true)
  for (const target of [
    '.config/media-missher/setup', '.config/media-missher/browser', '.config/media-missher/browser/chrome-profile',
    '.local/share/media-missher/current', '.local/share/media-missher/venv', '.local/share/media-missher/state', '.local/share/media-missher/.staging',
    '.local/share/media-missher-agent/runs/windows-alias', '.local/share/media-missher-shared',
  ]) {
    await syntheticWslMount(f, target)
    const result = f.run(['doctor'])
    assert.equal(result.status, 1, target)
    assert.equal(result.value.error, 'platform_wsl_native_storage_required', target)
  }
  assert.deepEqual(await readdir(f.home), [])
})

test('skill installation checks the backup mount before touching its isolated destination', async () => {
  const f = await fixture(true)
  await syntheticWslMount(f, '.local/share/media-missher-agent/skill-backups')
  const result = f.run(['install-skill', '--skill-root', join(f.home, 'skills')])
  assert.equal(result.status, 1)
  assert.equal(result.value.error, 'platform_wsl_native_storage_required')
  assert.deepEqual(await readdir(f.home), [])
})

test('skill installation keeps an unrelated Agent skill mount outside its storage scope', async () => {
  const f = await fixture(true)
  await syntheticWslMount(f, 'skills/unrelated')
  const root = join(f.home, 'skills')
  const result = f.run(['install-skill', '--skill-root', root])
  assert.equal(result.status, 0, result.stdout)
  assert.deepEqual(await readdir(root), ['media-missher'])
})

test('activation accepts more than four rows, several accounts on one platform and explicit targets', async () => {
  const f = await fixture(true)
  const { parseCli } = await import(pathToFileURL(entry))
  const rows = parseCli(['setup', 'activate', '--import-id', importId, '--rows', '1,2,3,4,5,6'])
  assert.deepEqual(rows.args.rows, [1, 2, 3, 4, 5, 6])
  assert.equal(rows.args.targets, undefined)
  const selected = parseCli(['setup', 'activate', '--import-id', importId, '--rows', '2,4', '--target', 'bilibili:creator:12345', '--target', 'bilibili:creator:67890', '--target', 'weibo:topic:旅行'])
  assert.deepEqual(selected.args.targets, [
    { platform: 'bilibili', mode: 'creator', uid: '12345' },
    { platform: 'bilibili', mode: 'creator', uid: '67890' },
    { platform: 'weibo', mode: 'topic', topic: '旅行', topic_kind: 'topic' },
  ])
  const onlyTargets = parseCli(['setup', 'activate', '--import-id', importId, '--target', 'x:creator:https://x.com/somebody'])
  assert.deepEqual(onlyTargets.args.rows, [])
  assert.deepEqual(onlyTargets.args.targets, [{ platform: 'x', mode: 'creator', homepage: 'https://x.com/somebody' }])
  // The removed four-row cap, the duplicate-row rule and the required selection still hold.
  assert.throws(() => parseCli(['setup', 'activate', '--import-id', importId, '--rows', '1,1']), /cli_arguments_invalid/u)
  assert.throws(() => parseCli(['setup', 'activate', '--import-id', importId]), /cli_arguments_invalid/u)
  assert.throws(() => parseCli(['setup', 'activate', '--import-id', importId, '--rows', Array.from({ length: 201 }, (unused, index) => index + 1).join(',')]), /cli_arguments_invalid/u)
  assert.throws(() => parseCli(['setup', 'activate', '--import-id', importId, '--target', 'x:topic:旅行']), error => error.code === 'target_topic_platform_invalid')
  const activated = f.run(['setup', 'activate', '--import-id', importId, '--rows', '1,2,3,4,5', '--target', 'weibo:topic:旅行'])
  assert.equal(activated.status, 0, activated.stderr)
  assert.deepEqual(activated.value.args, {
    action: 'activate', import_id: importId, rows: [1, 2, 3, 4, 5],
    targets: [{ platform: 'weibo', mode: 'topic', topic: '旅行', topic_kind: 'topic' }],
  })
})

test('collection accepts repeated targets, CDP, best_effort, a deadline and a weibo topic', async () => {
  const f = await fixture(true)
  const result = f.run(['collect', '--target', 'bilibili:creator:12345', '--target', 'bilibili:creator:67890', '--target', 'x:search:top:ai', '--topic', '旅行', '--backend', 'cdp', '--count-mode', 'best_effort', '--count', '50', '--run-deadline', '1800'])
  assert.equal(result.status, 0, result.stderr)
  assert.deepEqual(result.value.args, {
    targets: [
      { platform: 'bilibili', mode: 'creator', uid: '12345' },
      { platform: 'bilibili', mode: 'creator', uid: '67890' },
      { platform: 'x', mode: 'search', keyword: 'ai', sort: 'top' },
      { platform: 'weibo', mode: 'topic', topic: '旅行', topic_kind: 'topic' },
    ],
    backend: 'cdp', count_mode: 'best_effort', count: 50, run_deadline_seconds: 1800,
  })
  assert.deepEqual(f.run(['collect', '--backend', 'cdp']).value.args, { backend: 'cdp' })
  // Every previously supported option keeps its exact shape.
  assert.deepEqual(f.run(['collect', '--platforms', 'weibo,xhs', '--count', '2', '--xhs-comments', '3', '--allow-navigation', '--resume-run', 'run-fixture']).value.args,
    { platforms: 'xhs,weibo', count: 2, xhs_comments: 3, allow_navigation: true, resume_run: 'run-fixture' })
})

test('the --target syntax covers creator ids, handles, homepages, search sorts and the weibo super topic', async () => {
  const { parseCli } = await import(pathToFileURL(entry))
  const parsed = parseCli(['collect', '--target', 'bilibili:creator:12345', '--target', 'weibo:creator:@Somebody', '--target', 'x:creator:https://x.com/somebody', '--target', 'x:search:ai', '--target', 'x:search:top:ai:未来', '--target', 'weibo:topic:旅行', '--target', 'weibo:topic:super:旅行超话'])
  assert.deepEqual(parsed.args.targets, [
    { platform: 'bilibili', mode: 'creator', uid: '12345' },
    { platform: 'weibo', mode: 'creator', handle: 'Somebody' },
    { platform: 'x', mode: 'creator', homepage: 'https://x.com/somebody' },
    { platform: 'x', mode: 'search', keyword: 'ai' },
    { platform: 'x', mode: 'search', keyword: 'ai:未来', sort: 'top' },
    { platform: 'weibo', mode: 'topic', topic: '旅行', topic_kind: 'topic' },
    { platform: 'weibo', mode: 'topic', topic: '旅行超话', topic_kind: 'super' },
  ])
  // --platforms keeps its ordering behaviour and now knows x.
  assert.equal(parseCli(['collect', '--platforms', 'x,weibo,bilibili']).args.platforms, 'bilibili,weibo,x')
  for (const platforms of ['x,x', 'twitter', 'bilibili,']) assert.throws(() => parseCli(['collect', '--platforms', platforms]), /cli_arguments_invalid/u)
})

test('the xhs count ceiling is enforced in fixed mode only, where the runtime holds the batch policy', async () => {
  const f = await fixture(true)
  const best = f.run(['collect', '--platforms', 'xhs', '--count', '50', '--count-mode', 'best_effort'])
  assert.equal(best.status, 0, best.stderr)
  assert.deepEqual(best.value.args, { platforms: 'xhs', count_mode: 'best_effort', count: 50 })
  const byTarget = f.run(['collect', '--target', 'xhs:creator:abcdef0123456789abcdef01', '--count', '50', '--count-mode', 'best_effort'])
  assert.equal(byTarget.status, 0, byTarget.stderr)
  assert.equal(byTarget.value.args.count, 50)
  for (const args of [
    ['collect', '--platforms', 'xhs', '--count', '11'],
    ['collect', '--platforms', 'xhs', '--count', '11', '--count-mode', 'fixed'],
    ['collect', '--target', 'xhs:creator:abcdef0123456789abcdef01', '--count', '11'],
  ]) {
    const result = f.run(args)
    assert.equal(result.status, 2, `${args.join(' ')}: ${result.stdout}`)
    assert.equal(result.value.error, 'cli_arguments_invalid')
  }
  assert.equal(f.run(['collect', '--platforms', 'xhs', '--count', '10', '--count-mode', 'fixed']).status, 0)
})

test('native account identities reach the actual CLI without being parsed as X handles', async () => {
  const f = await fixture(true)
  for (const [platform, uid, homepage] of [
    ['xhs', 'abcdef0123456789abcdef01', 'https://www.xiaohongshu.com/user/profile/abcdef0123456789abcdef01'],
    ['douyin', 'MS4wLjABAAAA_abcdefghijklmnop', 'https://www.douyin.com/user/MS4wLjABAAAA_abcdefghijklmnop'],
  ]) {
    for (const [value, key] of [[uid, 'uid'], [homepage, 'homepage']]) {
      const result = f.run(['collect', '--target', `${platform}:creator:${value}`, '--count', '1'])
      assert.equal(result.status, 0, result.stdout)
      assert.deepEqual(result.value.args.targets, [{platform, mode:'creator', [key]:value}])
    }
  }
  for (const value of ['xhs:creator:12345', 'xhs:creator:not-a-hex-id', 'douyin:creator:..', 'douyin:creator:bad/value']) {
    const result = f.run(['collect', '--target', value])
    assert.equal(result.status, 2)
    assert.equal(result.value.error, 'target_uid_invalid')
  }
})

test('target, backend, count-mode and export options stay exhaustively strict', async () => {
  const f = await fixture()
  const invalid = [
    ['collect', '--no-allow-navigation'], ['collect', '--targets', 'x:creator:1'],
    ['collect', '--backend'], ['collect', '--backend', '--count', '1'],
    ['collect', '--backend', 'browserskill', '--backend', 'cdp'],
    ['collect', '--count-mode', 'endless'], ['collect', '--count', '501'], ['collect', '--count', '0'],
    ['collect', '--run-deadline', '0'], ['collect', '--run-deadline', '86401'],
    ['collect', '--target'], ['collect', '--target', 'nonsense'], ['collect', '--target', 'youtube:creator:1'],
    ['collect', '--target', 'bilibili:creator:12-345'], ['collect', '--target', 'x:search:'],
    ['collect', '--target', 'x:creator:12345', '--target', 'x:creator:12345'],
    ['collect', '--topic', '--count', '1'], ['collect', '--topic', ''],
    ['runs', 'export', '--run-id', 'run-one', '--format', 'pdf'],
    ['runs', 'export', '--run-id', 'run-one', '--record-kinds', 'comments'],
    ['runs', 'export', '--run-id', 'run-one', '--file-name', '../private.xlsx'],
    ['runs', 'export', '--run-id', 'run-one', '--targets', 'weibo:topic:旅行', '--targets', 'weibo:topic:旅行'],
    ['runs', 'export', '--run-id', 'run-one', '--record-kinds', 'posts', '--record-kinds', 'posts'],
    ['setup', 'activate', '--import-id', importId],
    ['setup', 'activate', '--import-id', importId, '--target', 'x:topic:旅行'],
  ]
  for (const args of invalid) {
    const result = f.run(args)
    assert.equal(result.status, 2, `${args.join(' ')}: ${result.stdout} ${result.stderr}`)
    assert.ok(['cli_arguments_invalid', ...TARGET_ERROR_CODES].includes(result.value.error), `${args.join(' ')}: ${result.value.error}`)
    assert.doesNotMatch(result.stdout + result.stderr, /Error:| at |SECRET/u)
  }
  assert.deepEqual(await readdir(f.home), [])
})

test('runs export validates the new selection and passes it to the shared library as args.export', async () => {
  const f = await fixture(true)
  const result = f.run(['runs', 'export', '--run-id', 'run-one', '--format', 'xlsx', '--record-kinds', 'posts,topic_participants', '--platforms', 'weibo,x', '--topics', '旅行', '--targets', 'weibo:topic:旅行', '--fields', 'tweet_id,author_id', '--field-groups', 'engagement', '--file-name', 'selected.xlsx'])
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.value.kind, 'runs', 'export must use the offline runs tool and never the collector')
  assert.deepEqual(result.value.args, {
    action: 'export', run_id: 'run-one', format: 'xlsx',
    export: {
      run_id: 'run-one', record_kinds: ['posts', 'topic_participants'], platforms: ['weibo', 'x'], topics: ['旅行'],
      targets: ['weibo:topic:topic:旅行'], fields: ['tweet_id', 'author_id'], field_groups: ['engagement'],
      format: 'xlsx', file_name: 'selected.xlsx', overwrite: false,
    },
  })
  const minimal = f.run(['runs', 'export', '--run-id', 'run-one', '--format', 'xlsx', '--record-kinds', 'posts', '--fields', 'tweet_id'])
  assert.equal(minimal.status, 0, minimal.stderr)
  assert.deepEqual(minimal.value.args.export, { run_id: 'run-one', record_kinds: ['posts'], platforms: [], topics: [], targets: [], fields: ['tweet_id'], field_groups: [], format: 'xlsx', overwrite: false })
  const overwrite = f.run(['runs', 'export', '--run-id', 'run-one', '--overwrite'])
  assert.equal(overwrite.value.args.export.overwrite, true)
  assert.equal(overwrite.value.args.export.format, 'xlsx')
  assert.equal(overwrite.value.args.export.record_kinds.join(','), 'posts')
  assert.deepEqual(f.run(['runs', 'export', '--run-id', 'run-one', '--format', 'xlsx']).value.args.export.platforms, [])
  // The historical minimal shape is unchanged and never carries the new object.
  assert.deepEqual(f.run(['runs', 'export', '--run-id', 'run-one', '--format', 'json']).value.args, { action: 'export', run_id: 'run-one', format: 'json' })
  assert.deepEqual(f.run(['runs', 'export', '--run-id', 'run-one', '--format', 'sqlite']).value.args, { action: 'export', run_id: 'run-one', format: 'sqlite' })
})

test('help documents the five platforms, targets, frozen backend, two count modes and the offline export', async () => {
  const f = await fixture()
  const result = f.run(['--help'])
  assert.equal(result.status, 0, result.stderr)
  assert.equal(result.value.status, 'ok')
  const help = JSON.stringify(result.value)
  for (const phrase of [
    'bilibili,xhs,douyin,weibo,x', 'PLATFORM:creator:UID|@handle|https://homepage', 'weibo:topic:super:NAME',
    'four-row limit is gone', 'never switches accounts automatically',
    '--count-mode fixed|best_effort', 'run-deadline', 'budget pause is not',
    '--backend cdp', 'no auto value and no silent fallback', 'Chrome CDP is the only backend', 'backend-retired-computer-use', 'backend-retired-browserskill',
    'xlsx|csv|json|jsonl|sqlite', '--record-kinds posts,topic_participants,user_profiles', 'never collects',
    'args.export',
  ]) assert.ok(help.includes(phrase), `--help must describe ${phrase}`)
  assert.deepEqual(result.value.exitCodes, { success: 0, failureOrPartial: 1, invalidArguments: 2, needsSetupOrPreflight: 3, riskStopped: 4, SIGINT: 130, SIGTERM: 143 })
})
