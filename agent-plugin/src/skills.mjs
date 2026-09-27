import { constants } from 'node:fs'
import { createHash, randomBytes } from 'node:crypto'
import { lstat, mkdir, open, readdir, rename, rmdir, unlink } from 'node:fs/promises'
import { dirname, isAbsolute, join, parse, resolve } from 'node:path'

const OWNER = '@missher/media-missher'
const MARKER = '.media-missher-install.json'
const FILES = ['SKILL.md', MARKER]
const digest = bytes => createHash('sha256').update(bytes).digest('hex')
const owned = stat => process.getuid === undefined || stat.uid === process.getuid()
const missing = error => error.code === 'ENOENT'

export class SkillInstallError extends Error {
  constructor(code, path = '') { super(code); this.code = code; this.path = path }
}
const fail = (code, path) => { throw new SkillInstallError(code, path) }

function absolute(value) {
  if (typeof value !== 'string' || !value || !isAbsolute(value) || value !== resolve(value) || value === parse(value).root || /[\u0000-\u001f\u007f]/u.test(value)) fail('skill_path_unsafe')
  return value
}

/** Agent-native user destinations; only the explicitly selected target is installed. */
export function listAgents(home, env = {}) {
  absolute(home)
  // Verified vendor docs: code.claude.com/docs/en/skills, cursor.com/docs/skills,
  // docs.openclaw.ai/tools/skills, hermes-agent.nousresearch.com/docs/user-guide/features/skills/.
  return [
    { name: 'codex', skillRoot: join(env.CODEX_HOME ? absolute(env.CODEX_HOME) : join(home, '.codex'), 'skills') },
    { name: 'claude', skillRoot: join(home, '.claude', 'skills') },
    { name: 'cursor', skillRoot: join(home, '.cursor', 'skills') },
    { name: 'openclaw', skillRoot: join(home, '.openclaw', 'skills') },
    { name: 'hermes', skillRoot: join(home, '.hermes', 'skills') },
  ]
}

async function checkPath(path) {
  absolute(path)
  for (let current = path; ; current = dirname(current)) {
    try {
      const stat = await lstat(current)
      if (stat.isSymbolicLink() || (current !== path && !stat.isDirectory())) fail('skill_path_unsafe', path)
    } catch (error) { if (!missing(error)) throw error }
    if (dirname(current) === current) break
  }
}

/** Create missing private directories, without repairing permissions on existing paths. */
async function directory(path, privateOnly = false) {
  await checkPath(path)
  try { await mkdir(path, { mode: 0o700 }) } catch (error) {
    if (missing(error)) {
      const parent = dirname(path)
      if (parent === parse(path).root) fail('skill_path_unsafe', path)
      await directory(parent)
      try { await mkdir(path, { mode: 0o700 }) } catch (nested) { if (nested.code !== 'EEXIST') throw nested }
    } else if (error.code !== 'EEXIST') throw error
  }
  const stat = await lstat(path)
  if (!stat.isDirectory() || stat.isSymbolicLink() || !owned(stat) || (stat.mode & 0o022) !== 0 || (privateOnly && (stat.mode & 0o777) !== 0o700)) fail('skill_path_unsafe', path)
  return stat
}

async function readSafeFile(path, limit, privateOnly = true) {
  await checkPath(path)
  const file = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK)
  try {
    const before = await file.stat()
    const valid = stat => stat.isFile() && owned(stat) && stat.nlink === 1 && (privateOnly ? (stat.mode & 0o777) === 0o600 : (stat.mode & 0o022) === 0)
    if (!valid(before) || before.size > limit) fail('skill_conflict', dirname(path))
    const bytes = Buffer.alloc(limit + 1)
    let length = 0
    while (length < bytes.length) {
      const { bytesRead } = await file.read(bytes, length, bytes.length - length, null)
      if (bytesRead === 0) break
      length += bytesRead
    }
    const after = await file.stat()
    const current = await lstat(path)
    await checkPath(path)
    if (length > limit || !valid(after) || !valid(current) || before.dev !== current.dev || before.ino !== current.ino || before.size !== after.size || before.mtimeMs !== after.mtimeMs || before.ctimeMs !== after.ctimeMs) fail('skill_conflict', dirname(path))
    return bytes.subarray(0, length)
  } finally { await file.close() }
}

async function writePrivateFile(path, bytes) {
  await checkPath(path)
  const file = await open(path, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600)
  try { await file.writeFile(bytes); await file.sync() } finally { await file.close() }
}

async function snapshot(path) {
  await checkPath(path)
  let stat
  try { stat = await lstat(path) } catch (error) { if (missing(error)) return undefined; throw error }
  if (!stat.isDirectory() || !owned(stat) || (stat.mode & 0o777) !== 0o700) fail('skill_conflict', path)
  if (JSON.stringify((await readdir(path)).sort()) !== JSON.stringify([...FILES].sort())) fail('skill_conflict', path)
  const bytes = {}
  for (const name of FILES) bytes[name] = await readSafeFile(join(path, name), name === MARKER ? 4096 : 96 * 1024)
  let marker
  try { marker = JSON.parse(bytes[MARKER].toString('utf8')) } catch { fail('skill_conflict', path) }
  if (!marker || typeof marker !== 'object' || Array.isArray(marker)
    || Object.keys(marker).sort().join(',') !== 'files,owner,schema,version' || marker.schema !== 1 || marker.owner !== OWNER
    || typeof marker.version !== 'string' || !/^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$/u.test(marker.version)
    || !marker.files || typeof marker.files !== 'object' || Array.isArray(marker.files)
    || Object.keys(marker.files).join(',') !== 'SKILL.md' || marker.files['SKILL.md'] !== digest(bytes['SKILL.md'])) fail('skill_conflict', path)
  return { stat, bytes }
}

function sameBytes(first, second) { return FILES.every(name => first[name].equals(second[name])) }
function sameSnapshot(first, second) {
  return first === undefined ? second === undefined : second !== undefined && first.stat.dev === second.stat.dev && first.stat.ino === second.stat.ino && sameBytes(first.bytes, second.bytes)
}

function shellQuote(value) {
  absolute(value)
  if (value.includes('```')) fail('skill_path_unsafe')
  return `'${value.replaceAll("'", "'\\''")}'`
}

async function stage(path, bytes) {
  await checkPath(path)
  await mkdir(path, { mode: 0o700 })
  try { for (const name of FILES) await writePrivateFile(join(path, name), bytes[name]) }
  catch (error) {
    for (const name of FILES) await unlink(join(path, name)).catch(failure => { if (!missing(failure)) throw failure })
    await rmdir(path)
    throw error
  }
}

async function removeSnapshot(path, expected) {
  if (!sameSnapshot(expected, await snapshot(path))) fail('skill_conflict', path)
  for (const name of FILES) await unlink(join(path, name))
  await rmdir(path)
}

/** A digest-owned copy upgrades transactionally; unrecognized or edited skills are preserved. */
export async function installSkill({ agent, skillRoot, home, env = {}, packageRoot, version, cliPath, nodePath, signal = new AbortController().signal }) {
  const root = absolute(skillRoot ?? listAgents(home, env).find(item => item.name === agent)?.skillRoot)
  const target = join(root, 'media-missher')
  signal.throwIfAborted()
  await checkPath(root)
  const template = (await readSafeFile(join(packageRoot, 'skill/SKILL.md'), 64 * 1024, false)).toString('utf8')
  if (!template.includes('{{MEDIA_MISSHER_COMMAND}}')) fail('skill_template_invalid')
  const skill = Buffer.from(template.replaceAll('{{MEDIA_MISSHER_COMMAND}}', `${shellQuote(nodePath)} ${shellQuote(cliPath)}`))
  const marker = Buffer.from(`${JSON.stringify({ schema: 1, owner: OWNER, version, files: { 'SKILL.md': digest(skill) } }, null, 2)}\n`)
  const nextBytes = { 'SKILL.md': skill, [MARKER]: marker }
  // Check an existing destination before creating a lock, backup or staging directory.
  await snapshot(target)
  await directory(root)
  const lockPath = join(root, '.media-missher-install.lock')
  let lock
  try { lock = await open(lockPath, constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL | constants.O_NOFOLLOW, 0o600) }
  catch (error) { if (['EEXIST', 'ELOOP'].includes(error.code)) fail('skill_install_busy', lockPath); throw error }
  const lockStat = await lock.stat()
  const nonce = `${Date.now()}-${randomBytes(8).toString('hex')}`
  const pending = join(root, `.media-missher-stage-${nonce}`)
  const previous = join(root, `.media-missher-previous-${nonce}`)
  let pendingSnapshot
  let prior
  let movedPrior = false
  let switched = false
  let backupPath = ''
  try {
    signal.throwIfAborted()
    prior = await snapshot(target)
    if (prior && sameBytes(prior.bytes, nextBytes)) return { status: 'ok', action: 'unchanged', path: target, backupPath: '', activation: 'Verify discovery in the intended Agent; installation does not activate the current conversation.' }
    await stage(pending, nextBytes)
    pendingSnapshot = await snapshot(pending)
    signal.throwIfAborted()
    if (prior) {
      const backupRoot = join(absolute(home), '.local/share/media-missher-agent/skill-backups')
      await directory(backupRoot, true)
      backupPath = join(backupRoot, `media-missher-${nonce}`)
      const backupPending = join(backupRoot, `.staging-${nonce}`)
      await stage(backupPending, prior.bytes)
      await rename(backupPending, backupPath)
    }
    signal.throwIfAborted()
    if (!sameSnapshot(prior, await snapshot(target))) fail('skill_conflict', target)
    if (prior) {
      await rename(target, previous)
      movedPrior = true
      if (!sameSnapshot(prior, await snapshot(previous))) fail('skill_conflict', previous)
    }
    try { await lstat(target); fail('skill_conflict', target) } catch (error) { if (!missing(error)) throw error }
    await rename(pending, target)
    switched = true
    if (!sameSnapshot(pendingSnapshot, await snapshot(target))) fail('skill_conflict', target)
    if (movedPrior) { await removeSnapshot(previous, prior); movedPrior = false }
    return { status: 'ok', action: prior ? 'updated' : 'installed', path: target, backupPath, activation: 'Verify discovery in the intended Agent; installation does not activate the current conversation.' }
  } catch (error) {
    if (movedPrior && !switched) {
      try {
        await lstat(target)
      } catch (failure) { if (missing(failure)) { await rename(previous, target); movedPrior = false } else throw failure }
    }
    if (error instanceof SkillInstallError || signal.aborted) throw error
    fail('skill_install_failed', target)
  } finally {
    try { if (!switched && pendingSnapshot) await removeSnapshot(pending, pendingSnapshot) }
    finally {
      await lock.close()
      const current = await lstat(lockPath).catch(error => { if (!missing(error)) throw error })
      if (current?.dev === lockStat.dev && current.ino === lockStat.ino) await unlink(lockPath)
    }
  }
}
