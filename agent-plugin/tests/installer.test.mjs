import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { gzipSync } from 'node:zlib'
import { mkdtemp, mkdir, readFile, readdir, realpath, rm, writeFile, symlink } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { inspectArchive, REQUIRED_PAYLOAD } from '../scripts/archive.mjs'
import { install, runInstallerProcess } from '../scripts/install.mjs'

function archive(overrides = {}, extra = [], omit = []) {
  const manifest = { name: '@missher/media-missher', version: '17.0.2', type: 'module', bin: { 'media-missher': 'bin/media-missher.mjs' }, license: 'SEE LICENSE IN LICENSE', dependencies: { exceljs: '4.4.0', saxes: '5.0.1' }, ...overrides }
  const files = [['package.json', JSON.stringify(manifest)], ['bin/media-missher.mjs', 'console.log("17.0.2")'], ['src/skills.mjs', '// skill installer'], ['src/platform.mjs', '// platform'], ['src/targets.mjs', '// target contract'], ['lib/index.js', '// shared core'], ['skill/SKILL.md', 'Skill contract'], ['LICENSE', 'Missher'], ['THIRD_PARTY_NOTICES.md', 'Notices'], ['payload/VERSION', '17.0.2\n'], ['payload/tools/install_media_missher.py', '# payload'], ...extra]
  for (const name of REQUIRED_PAYLOAD) if (!files.some(([path]) => path === name)) files.push([name, name.endsWith('.media-missher-source-tree') ? 'media-missher-source-v1\n' : '# fixture'])
  files.push(['src/capabilities.mjs', '// host-neutral lifecycle'])
  const parts = []
  for (const [name, text, type = '0'] of files.filter(([name]) => !omit.includes(name))) {
    const body = Buffer.from(text), header = Buffer.alloc(512)
    header.write(`package/${name}`, 0); header.write('0000644\0', 100)
    header.write('0000000\0', 108); header.write('0000000\0', 116)
    header.write(body.length.toString(8).padStart(11, '0') + '\0', 124)
    header.write('00000000000\0', 136); header.fill(32, 148, 156)
    header.write(type, 156); header.write('ustar\0', 257); header.write('00', 263)
    header.write([...header].reduce((sum, value) => sum + value, 0).toString(8).padStart(6, '0') + '\0 ', 148)
    parts.push(header, body, Buffer.alloc((512 - body.length % 512) % 512))
  }
  return gzipSync(Buffer.concat([...parts, Buffer.alloc(1024)]))
}
async function fixture(t, bytes = archive()) {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-agent-install-')))
  t.after(() => rm(root, { recursive: true, force: true }))
  const file = join(root, 'package.tgz'); await writeFile(file, bytes)
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  return { root, bytes, options: { archive: file, sha256, home: join(root, 'install'), binDir: join(root, 'bin') } }
}
function fakeRunner(bytes) {
  const { files } = inspectArchive(bytes)
  return async (command, args, options) => {
    if (command !== 'npm') return 'Media@Missher CLI 17.0.2\n'
    const root = join(options.cwd, 'node_modules/@missher/media-missher')
    for (const [name, body] of files) {
      const path = join(root, name.slice(8))
      await mkdir(dirname(path), { recursive: true }); await writeFile(path, body)
    }
    return ''
  }
}

test('archive gate rejects paths, links, duplicate members, extra runtime hooks and malformed headers', () => {
  assert.equal(inspectArchive(archive()).manifest.version, '17.0.2')
  for (const bytes of [archive({}, [['../profile.json', 'private']]), archive({}, [['payload/runtime/../profile.json', 'private']]), archive({}, [['lib/index.js', 'changed']]), archive({}, [['payload/runtime/linked.py', 'target', '2']]), archive({ scripts: { preinstall: 'echo unexpected' } }), archive({ name: 'someone-else' }), Buffer.from('not gzip')]) assert.throws(() => inspectArchive(bytes))
})

test('wrong checksum and wrong package identity stop before writing an install directory', async t => {
  const f = await fixture(t)
  await assert.rejects(install({ ...f.options, sha256: '0'.repeat(64) }), /install_checksum_mismatch/)
  assert.deepEqual(await readdir(f.root), ['package.tgz'])
  const g = await fixture(t, archive({ name: 'unrelated' }))
  await assert.rejects(install(g.options), /archive_manifest_invalid/)
  assert.deepEqual(await readdir(g.root), ['package.tgz'])
})

test('an unknown existing directory or launcher is never adopted or replaced', async t => {
  const f = await fixture(t)
  await mkdir(f.options.home, { mode: 0o700 }); await writeFile(join(f.options.home, 'keep'), 'keep')
  await assert.rejects(install(f.options), /install_directory_unknown/)
  assert.equal(await readFile(join(f.options.home, 'keep'), 'utf8'), 'keep')
  const g = await fixture(t)
  await mkdir(g.options.binDir, { mode: 0o700 }); await writeFile(join(g.options.binDir, 'media-missher'), 'unrelated', { mode: 0o700 })
  await assert.rejects(install(g.options), /install_launcher_conflict/)
  assert.equal(await readFile(join(g.options.binDir, 'media-missher'), 'utf8'), 'unrelated')
})

test('a symlinked destination is rejected', async t => {
  const f = await fixture(t)
  await mkdir(join(f.root, 'elsewhere'), { mode: 0o700 }); await symlink(join(f.root, 'elsewhere'), f.options.home)
  await assert.rejects(install(f.options), /install_path_symlink/)
  assert.deepEqual(await readdir(join(f.root, 'elsewhere')), [])
})

test('successful staged install preserves exact launcher/state on a failed subsequent dependency install', async t => {
  const f = await fixture(t)
  const value = await install(f.options, { run: fakeRunner(f.bytes) })
  const launcher = await readFile(value.executable), state = await readFile(join(f.options.home, '.current.json'))
  await assert.rejects(install(f.options, { run: async () => { throw new Error('network_fixture_failed') } }), /network_fixture_failed/)
  assert.deepEqual(await readFile(value.executable), launcher)
  assert.deepEqual(await readFile(join(f.options.home, '.current.json')), state)
  assert.equal((await readdir(join(f.options.home, 'releases'))).length, 1)
  assert.equal((await readdir(f.options.home)).includes('.install.lock'), false)
  const upgraded = await install(f.options, { run: fakeRunner(f.bytes) })
  assert.notEqual(upgraded.release, value.release)
  assert.deepEqual(await readFile(join(upgraded.release, 'previous-launcher')), launcher)
  assert.deepEqual(await readFile(join(upgraded.release, 'previous-state.json')), state)
})

test('aborted installation and mismatched installed payload never activate a command', async t => {
  const f = await fixture(t), controller = new AbortController()
  controller.abort()
  await assert.rejects(install({ ...f.options, signal: controller.signal }))
  assert.deepEqual(await readdir(f.root), ['package.tgz'])
  await assert.rejects(install(f.options, { run: async (...args) => {
    await fakeRunner(f.bytes)(...args)
    await writeFile(join(args[2].cwd, 'node_modules/@missher/media-missher/lib/index.js'), 'tampered')
    return ''
  } }), /install_payload_mismatch/)
  assert.deepEqual(await readdir(f.options.binDir), [])
})

test('different installation roots cannot concurrently take over the same command directory', async t => {
  const f = await fixture(t)
  let entered, unblock
  const ready = new Promise(resolve => { entered = resolve })
  const hold = new Promise(resolve => { unblock = resolve })
  const first = install(f.options, { run: async (...args) => {
    if (args[0] === 'npm') { entered(); await hold }
    return fakeRunner(f.bytes)(...args)
  } })
  await ready
  try { await assert.rejects(install({ ...f.options, home: join(f.root, 'another-install') }, { run: fakeRunner(f.bytes) }), /install_busy/) }
  finally { unblock() }
  assert.equal((await first).status, 'ok')
})


test('every runtime member is required before activation even when its checksum is valid', async t => {
  for (const member of REQUIRED_PAYLOAD) {
    const incomplete = archive({}, [], [member])
    assert.throws(() => inspectArchive(incomplete), /archive_incomplete/)
  }
  const f = await fixture(t, archive({}, [], ['payload/media-missher/scripts/run_collection.py']))
  await assert.rejects(install(f.options, { run: () => { throw new Error('must_not_execute') } }), /archive_incomplete/)
  assert.deepEqual(await readdir(f.root), ['package.tgz'])
})

test('cancel waits for a SIGTERM-resistant descendant after its group leader closes', { timeout: 10000 }, async t => {
  const f = await fixture(t), controller = new AbortController()
  const readyFile = join(f.root, 'child-ready.json')
  const childScript = `
    const { writeFileSync } = require('node:fs');
    process.on('SIGTERM', () => {});
    writeFileSync(${JSON.stringify(readyFile)}, JSON.stringify({ pid: process.pid, pgid: process.ppid }));
    setInterval(() => {}, 1000);
  `
  const parentScript = `
    const { spawn } = require('node:child_process');
    spawn(process.execPath, ['-e', ${JSON.stringify(childScript)}], { stdio: 'ignore' });
    setInterval(() => {}, 1000);
  `
  const result = runInstallerProcess(process.execPath, ['-e', parentScript], { cwd: f.root, signal: controller.signal })
    .then(() => ({ succeeded: true }), error => ({ error }))
  let owned
  const state = () => {
    const observed = spawnSync('/bin/ps', ['-p', String(owned.pid), '-o', 'pgid=,stat='], { encoding: 'utf8', timeout: 1000, shell: false })
    assert.ifError(observed.error)
    assert.ok([0, 1].includes(observed.status))
    const match = /^\s*(\d+)\s+(\S+)/.exec(observed.stdout)
    return match && Number(match[1]) === owned.pgid && !match[2].startsWith('Z')
  }
  try {
    const deadline = Date.now() + 5000
    while (!owned) {
      try { owned = JSON.parse(await readFile(readyFile, 'utf8')) }
      catch (error) { if (error.code !== 'ENOENT') throw error }
      if (Date.now() >= deadline) throw new Error('fixture_child_not_ready')
      if (!owned) await new Promise(resolve => setTimeout(resolve, 20))
    }
    assert.ok(state())
    controller.abort()
    const outcome = await result
    assert.match(outcome.error?.message ?? '', /install_cancelled/, outcome.error?.cause?.message)
    assert.notEqual(outcome.error.preserveRelease, true)
    assert.ok(!state(), 'runner must settle only after its owned descendant has stopped')
  } finally {
    controller.abort()
    if (owned && state()) {
      try { process.kill(-owned.pgid, 'SIGKILL') } catch (error) { if (error.code !== 'ESRCH') throw error }
    }
    await result
  }
})
