#!/usr/bin/env node
// Installed artifact acceptance; private temporary HOME, no platform or browser requests.
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { createHash } from 'node:crypto'
import { lstat, mkdir, mkdtemp, readFile, realpath, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const args = process.argv.slice(2)
if (args.length && (args.length !== 2 || args[0] !== '--dist')) throw new Error('usage: native-smoke.mjs [--dist <directory>]')
const distribution = args.length ? resolve(args[1]) : join(packageRoot, 'dist')
const metadata = JSON.parse(await readFile(join(distribution, 'PACKAGE.json'), 'utf8'))
const temporary = await realpath(await mkdtemp(join(tmpdir(), 'media-agent-native-')))
const home = join(temporary, 'home')
await mkdir(home, { mode: 0o700 })
const env = { ...process.env, HOME: home, PYTHONDONTWRITEBYTECODE: '1' }
for (const key of Object.keys(env)) if (/^(?:MEDIA_MISSHER_|DSH_HOME$|CODEX_HOME$|TEST_)/.test(key)) delete env[key]
const run = (command, args, cwd = temporary) => new Promise((done, reject) => {
  const child = spawn(command, args, { cwd, env, shell: false, stdio: ['ignore', 'pipe', 'pipe'] })
  let stdout = '', stderr = ''
  child.stdout.on('data', data => { stdout += data })
  child.stderr.on('data', data => { stderr += data })
  child.once('error', reject)
  child.once('close', code => {
    let value
    try { value = JSON.parse(stdout) } catch {}
    done({ code, value, stderr })
  })
})
const absent = async path => { await assert.rejects(lstat(path), { code: 'ENOENT' }) }
const checks = []
let report
const setupBytes = await readFile(join(distribution, metadata.setupFile))
assert.equal(createHash('sha256').update(setupBytes).digest('hex'), metadata.setupSha256)
const archiveBytes = await readFile(join(distribution, metadata.packageFile))
assert.equal(createHash('sha256').update(archiveBytes).digest('hex'), metadata.packageSha256)
try {
  const unpack = await run('python3', ['-c', 'import zipfile,sys;zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])', join(distribution, metadata.setupFile), temporary])
  assert.equal(unpack.code, 0)
  const setup = join(temporary, 'Media-Missher-Agent-Setup')
  const installed = await run('sh', [join(setup, 'install.sh'), '--archive', join(setup, metadata.packageFile), '--sha256', metadata.packageSha256])
  assert.equal(installed.code, 0, JSON.stringify(installed.value))
  assert.equal(installed.value.status, 'ok')
  checks.push('actual Setup shell installer, registry dependencies, immutable package bytes and activation')
  const cli = installed.value.executable
  const invoke = args => run(cli, args)
  const version = await invoke(['--version'])
  assert.equal(version.code, 0)
  assert.equal(version.value.version, metadata.version)
  assert.equal(version.value.runtimeRequired, metadata.runtimeVersion)
  assert.equal((await invoke(['--help'])).code, 0)
  checks.push('installed executable launcher and exact component versions')
  const capability = await invoke(['capabilities'])
  assert.equal(capability.code, 0)
  assert.deepEqual(Object.keys(capability.value.backends), ['cdp'])
  assert.equal(capability.value.backends.cdp.ready, false)
  for (const action of ['prepare', 'ingest', 'status', 'finalize', 'cancel']) {
    const refused = await invoke(['computer-use', action])
    assert.equal(refused.code, 2)
    assert.equal(refused.value.error, 'cli_arguments_invalid')
  }
  checks.push('installed CDP-only declaration and removed commands refuse before setup')
  const doctor = await invoke(['doctor'])
  assert.equal(doctor.code, 3)
  assert.equal(doctor.value.status, 'needs-setup')
  assert.equal(doctor.value.browser.status, 'not-checked')
  const blank = await invoke(['collect', '--platforms', 'xhs', '--count', '1'])
  assert.equal(blank.code, 3)
  assert.equal(blank.value.status, 'needs-input')
  assert.deepEqual(blank.value.missingFields, ['targets'])
  await absent(join(home, '.local/share/media-missher'))
  await absent(join(home, '.local/share/media-missher-agent/runs'))
  await absent(join(home, '.config/media-missher'))
  checks.push('blank doctor and blank collection keep runtime, target profile and runs absent')
  const skill = await invoke(['install-skill', '--agent', 'codex'])
  assert.equal(skill.code, 0)
  assert.equal((await invoke(['install-skill', '--agent', 'codex'])).value.action, 'unchanged')
  const skillFile = join(skill.value.path, 'SKILL.md'), skillBytes = await readFile(skillFile)
  assert.match(skillBytes.toString(), /runtime 17\.0\.0/)
  assert.ok(!skillBytes.toString().includes('{{MEDIA_MISSHER_COMMAND}}'))
  checks.push('Codex Skill installed with absolute command fallback and idempotent reinstall')
  const template = await invoke(['setup', 'template'])
  assert.equal(template.code, 0)
  assert.ok((await lstat(template.value.artifactPath)).size > 1000)
  const roster = join(home, 'creators.csv')
  await writeFile(roster, '平台,博主名称,主页链接\n微博,Offline Fixture,https://weibo.com/u/1234567890\n', { mode: 0o600 })
  const imported = await invoke(['setup', 'import', '--file', roster])
  assert.equal(imported.code, 0, JSON.stringify(imported.value))
  const selected = await invoke(['setup', 'activate', '--import-id', imported.value.importId, '--rows', '1'])
  assert.equal(selected.code, 0)
  assert.equal(selected.value.activePlatforms, 'weibo')
  assert.equal((await invoke(['setup', 'status'])).value.browserStatus, 'not-checked')
  await absent(join(home, '.local/share/media-missher'))
  await absent(join(home, '.config/media-missher/browser'))
  await absent(join(home, '.local/share/media-missher-shared'))
  checks.push('real Excel template, synthetic CSV import/preview/activation; no runtime/browser/shared state')
  await writeFile(skillFile, Buffer.concat([skillBytes, Buffer.from('\nUser edit\n')]), { mode: 0o600 })
  const conflict = await invoke(['install-skill', '--agent', 'codex'])
  assert.notEqual(conflict.code, 0)
  assert.match((await readFile(skillFile)).toString(), /User edit/)
  checks.push('edited existing Skill preserved on conflict')
  report = { status: 'passed', platform: process.platform, arch: process.arch, node: process.versions.node, packageSha256: metadata.packageSha256, setupSha256: metadata.setupSha256, checks, realPlatformRequests: 0, browserLaunches: 0, syntheticCreators: 1, harnessInvoked: false, isolatedHarnessProfileCreated: false, hostSkillActivationVerified: false }
} finally { await rm(temporary, { recursive: true, force: true }) }
await absent(temporary)
report.temporaryHomeRemoved = true
await mkdir(join(packageRoot, '.work'), { recursive: true })
await writeFile(join(packageRoot, '.work/native-smoke.json'), JSON.stringify(report, null, 2) + '\n')
process.stdout.write(JSON.stringify(report, null, 2) + '\n')
