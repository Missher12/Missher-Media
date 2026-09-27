// Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
import { readFile } from 'node:fs/promises'
import { release } from 'node:os'
import { resolve, sep } from 'node:path'

export class StorageError extends Error {}
const within = (path, root) => path === root || path.startsWith(root + sep)
export function wslEnvironment({ platform = process.platform, kernel = release(), distribution = process.env.WSL_DISTRO_NAME } = {}) {
  return platform === 'linux' && (Boolean(distribution) || /microsoft/i.test(kernel))
}
export function assertWslStorage(home, paths, mountinfo) {
  if (!/^\/home\/[^/]+(?:\/|$)/.test(home) || paths.some(path => !within(resolve(path), home))) throw new StorageError('platform_wsl_home_required')
  if (typeof mountinfo !== 'string' || mountinfo.length > 512 * 1024) throw new StorageError('platform_wsl_storage_unverified')
  const decode = value => value.replace(/\\(040|011|012|134)/g, (_, code) => String.fromCharCode(Number.parseInt(code, 8)))
  const mounts = mountinfo.trim().split('\n').map(line => {
    const fields = line.split(' '), separator = fields.indexOf('-')
    if (separator < 6 || !fields[4]?.startsWith('/') || !fields[separator + 1]) throw new StorageError('platform_wsl_storage_unverified')
    return { path: decode(fields[4]), type: fields[separator + 1] }
  }).sort((a, b) => b.path.length - a.path.length)
  for (const path of [home, ...paths]) {
    const mount = mounts.find(item => item.path === '/' || within(resolve(path), item.path))
    // WSL2's distribution filesystem is ext4. Explicit native Linux alternatives are permitted.
    if (!mount || !['ext4', 'xfs', 'btrfs'].includes(mount.type)) throw new StorageError('platform_wsl_native_storage_required')
  }
  // A controlled directory may contain a bind-mounted browser profile, venv or state subdirectory.
  for (const path of paths) {
    if (mounts.some(mount => within(mount.path, resolve(path)) && !['ext4', 'xfs', 'btrfs'].includes(mount.type))) throw new StorageError('platform_wsl_native_storage_required')
  }
}
export async function checkStorage(home, paths, context = {}) {
  const platform = context.platform ?? process.platform
  if (platform === 'linux' && (context.uid ?? process.getuid?.()) === 0) throw new StorageError('platform_linux_user_required')
  if (!wslEnvironment(context)) return
  let mountinfo
  try { mountinfo = context.mountinfo ?? await readFile('/proc/self/mountinfo', 'utf8') }
  catch { throw new StorageError('platform_wsl_storage_unverified') }
  assertWslStorage(resolve(home), paths.map(path => resolve(path)), mountinfo)
}
