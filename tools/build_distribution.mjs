#!/usr/bin/env node
// Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
import { spawnSync } from 'node:child_process'
import { mkdir, readFile } from 'node:fs/promises'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { verifyPackage } from '../harness-plugin/scripts/verify-package.mjs'
import { inspectArchive } from '../agent-plugin/scripts/archive.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const version = (await readFile(join(root, 'VERSION'), 'utf8')).trim()
if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error('distribution_version_invalid')
const args = process.argv.slice(2)
let assembleOnly = false, validation
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--assemble-only') assembleOnly = true
  else if (args[i] === '--validation' && args[i + 1]) validation = resolve(args[++i])
  else throw new Error('usage: build_distribution.mjs [--assemble-only] [--validation <json>]')
}
for (const packageName of ['agent-plugin', 'harness-plugin']) {
  const manifest = JSON.parse(await readFile(join(root, packageName, 'package.json'), 'utf8'))
  if (manifest.version !== version || manifest.private !== true) throw new Error('distribution_component_version_mismatch')
}
const distribution = join(root, 'dist', `v${version}`)
await mkdir(distribution, { recursive: true })
function run(command, argv, cwd = root) {
  const result = spawnSync(command, argv, { cwd, stdio: 'inherit', shell: false, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } })
  if (result.error || result.status !== 0) throw new Error(`distribution_step_failed:${command}`)
}
if (!assembleOnly) {
  run('node', ['agent-plugin/scripts/build.mjs'])
  run('node', ['agent-plugin/scripts/build-setup.mjs', '--output', distribution])
  run('npm', ['pack', '--ignore-scripts', '--pack-destination', distribution], join(root, 'harness-plugin'))
}
await verifyPackage(join(distribution, `dsh-media-missher-${version}.tgz`))
inspectArchive(await readFile(join(distribution, `missher-media-missher-${version}.tgz`)))
run('python3', ['-B', 'tools/distribution_archive.py', '--root', root, ...(validation ? ['--validation', validation] : [])])
run('node', ['tools/verify_distribution.mjs', distribution])
console.log(`Private distribution ready: ${distribution}`)
