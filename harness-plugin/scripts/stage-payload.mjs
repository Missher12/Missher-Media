#!/usr/bin/env node

import {
  copyFile,
  lstat,
  mkdir,
  readdir,
  readFile,
  rm,
} from 'node:fs/promises'
import { basename, dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = resolve(pluginRoot, '..')

function parseOutput(args) {
  if (args.length === 0) return resolve(pluginRoot, 'payload')
  if (args.length !== 2 || args[0] !== '--output') throw new Error('usage: stage-payload.mjs [--output <payload>]')
  const output = resolve(args[1])
  if (basename(output) !== 'payload' || [pluginRoot, repositoryRoot, '/'].includes(output)) {
    throw new Error('payload_output_invalid')
  }
  return output
}

async function copyTree(source, target) {
  const metadata = await lstat(source)
  if (metadata.isSymbolicLink()) throw new Error(`payload_source_symlink:${source}`)
  if (metadata.isDirectory()) {
    await mkdir(target, { recursive: true })
    for (const name of await readdir(source)) {
      if (name === '__pycache__' || name.endsWith('.pyc')) continue
      await copyTree(resolve(source, name), resolve(target, name))
    }
    return
  }
  if (!metadata.isFile()) throw new Error(`payload_source_type_invalid:${source}`)
  await mkdir(dirname(target), { recursive: true })
  await copyFile(source, target)
}

const output = parseOutput(process.argv.slice(2))
await rm(output, { recursive: true, force: true })
await mkdir(output, { recursive: true })

await copyTree(resolve(repositoryRoot, 'VERSION'), resolve(output, 'VERSION'))
await copyTree(
  resolve(repositoryRoot, '.media-missher-source-tree'),
  resolve(output, '.media-missher-source-tree'),
)
await copyTree(resolve(repositoryRoot, 'runtime'), resolve(output, 'runtime'))
await copyTree(
  resolve(repositoryRoot, 'media-missher', 'scripts'),
  resolve(output, 'media-missher', 'scripts'),
)
for (const name of ['install_media_missher.py', 'scan_active_residuals.py']) {
  await copyTree(resolve(repositoryRoot, 'tools', name), resolve(output, 'tools', name))
}

if (await readFile(resolve(output, 'VERSION'), 'utf8') !== '15.2.1\n') {
  await rm(output, { recursive: true, force: true })
  throw new Error('payload_version_mismatch')
}
if (
  await readFile(resolve(output, '.media-missher-source-tree'), 'utf8')
  !== 'media-missher-source-v1\n'
) {
  await rm(output, { recursive: true, force: true })
  throw new Error('payload_source_identity_mismatch')
}

process.stdout.write(`${output}\n`)
