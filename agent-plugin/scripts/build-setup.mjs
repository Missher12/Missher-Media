#!/usr/bin/env node
// Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
import { createHash } from 'node:crypto'
import { cp, mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { inspectArchive } from './archive.mjs'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..'), repository = dirname(root)
const args = process.argv.slice(2)
if (args.length && (args.length !== 2 || args[0] !== '--output')) throw new Error('usage: build-setup.mjs [--output <directory>]')
const distribution = args.length ? resolve(args[1]) : join(root, 'dist')
await mkdir(distribution, { recursive: true })
const result = spawnSync('npm', ['pack', '--ignore-scripts', '--json', '--pack-destination', distribution], { cwd: root, encoding: 'utf8', shell: false })
if (result.error || result.status !== 0) throw new Error('agent_pack_failed')
const name = JSON.parse(result.stdout)[0].filename
if (!/^missher-media-missher-\d+\.\d+\.\d+\.tgz$/.test(name)) throw new Error('agent_archive_name_invalid')
const archive = await readFile(join(distribution, name))
const { manifest, files } = inspectArchive(archive)
const sha256 = createHash('sha256').update(archive).digest('hex')
const temporary = await mkdtemp(join(tmpdir(), 'media-agent-setup-'))
const folder = 'Media-Missher-Agent-Setup'
const stage = join(temporary, folder)
try {
  await mkdir(join(stage, 'agent-plugin/scripts'), { recursive: true })
  await mkdir(join(stage, 'agent-plugin/src'), { recursive: true })
  for (const path of ['install.sh', 'install.ps1', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'agent-plugin/scripts/install.mjs', 'agent-plugin/scripts/archive.mjs', 'agent-plugin/src/platform.mjs']) await cp(join(repository, path), join(stage, path))
  const guide = (await readFile(join(repository, 'AGENT_INSTALL.md'), 'utf8')).replaceAll('<exact SHA-256 from SHA256SUMS.txt>', sha256)
  await writeFile(join(stage, 'AGENT_INSTALL.md'), guide)
  for (const name of ['DATA_CAPABILITIES.md', 'QUICKSTART.md']) await cp(join(repository, name), join(stage, name))
  await cp(join(repository, 'examples'), join(stage, 'examples'), { recursive: true })
  await writeFile(join(stage, name), archive)
  await writeFile(join(stage, 'SHA256SUMS.txt'), `${sha256}  ${name}\n`)
  const zipName = `Media-Missher-Agent-Setup-v${manifest.version}.zip`
  const zip = spawnSync('python3', ['-c', 'import pathlib,zipfile,sys\nroot=pathlib.Path(sys.argv[1]);out=pathlib.Path(sys.argv[2])\nwith zipfile.ZipFile(out,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:\n for p in sorted(root.rglob("*")):\n  if not p.is_file(): continue\n  i=zipfile.ZipInfo(str(p.relative_to(root.parent)),(2026,9,8,0,0,0));i.compress_type=zipfile.ZIP_DEFLATED;i.external_attr=(0o100644<<16);z.writestr(i,p.read_bytes())', stage, join(distribution, zipName)], { encoding: 'utf8', shell: false })
  if (zip.error || zip.status !== 0) throw new Error('agent_setup_zip_failed')
  const zipBytes = await readFile(join(distribution, zipName))
  const zipSha256 = createHash('sha256').update(zipBytes).digest('hex')
  await writeFile(join(distribution, 'SHA256SUMS.txt'), `${sha256}  ${name}\n${zipSha256}  ${zipName}\n`)
  const summary = { package: manifest.name, version: manifest.version, runtimeVersion: files.get('package/payload/VERSION').toString().trim(), packageFile: name, packageBytes: archive.length, packageSha256: sha256, setupFile: zipName, setupBytes: zipBytes.length, setupSha256: zipSha256, fileCount: files.size, sourceRepository: 'private', publicDownload: null, windowsEntry: 'WSL2 with Linux Chrome in WSLg' }
  await writeFile(join(distribution, 'PACKAGE.json'), JSON.stringify(summary, null, 2) + '\n')
  process.stdout.write(JSON.stringify(summary, null, 2) + '\n')
} finally { await rm(temporary, { recursive: true, force: true }) }
