#!/usr/bin/env node
// Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
import { cp, mkdir, readFile, rm } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repository = resolve(root, '..')
const harness = join(repository, 'harness-plugin')
for (const args of [['run', 'build'], ['run', 'stage:payload']]) {
  const result = spawnSync('pnpm', args, { cwd: harness, stdio: 'inherit', shell: false })
  if (result.error || result.status !== 0) throw new Error('agent_shared_build_failed')
}
await mkdir(join(root, 'lib'), { recursive: true })
await cp(join(harness, 'lib/index.js'), join(root, 'lib/index.js'))
await rm(join(root, 'payload'), { recursive: true, force: true })
await cp(join(harness, 'payload'), join(root, 'payload'), { recursive: true })
for (const name of ['LICENSE', 'THIRD_PARTY_NOTICES.md', 'AGENT_INSTALL.md', 'DATA_CAPABILITIES.md', 'QUICKSTART.md']) await cp(join(repository, name), join(root, name))
const code = await readFile(join(root, 'lib/index.js'), 'utf8')
if (/(?:from\s*|import\s*\(|require\s*\()\s*['"]@deepseek-ai\//.test(code)) throw new Error('agent_host_runtime_dependency')
await mkdir(join(root, 'dist'), { recursive: true })
process.stdout.write('Agent package staged from the shared implementation.\n')
