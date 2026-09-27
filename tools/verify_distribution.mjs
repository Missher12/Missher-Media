#!/usr/bin/env node
// Copyright (c) 2026 Missher. All rights reserved. See LICENSE.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { inspectArchive } from '../agent-plugin/scripts/archive.mjs'
import { verifyPackage } from '../harness-plugin/scripts/verify-package.mjs'

const directory = resolve(process.argv[2] ?? 'dist/v17.0.0')
const digest = bytes => createHash('sha256').update(bytes).digest('hex')
const manifest = JSON.parse(await readFile(join(directory, 'PACKAGE.json'), 'utf8'))
assert.equal(manifest.private, true)
for (const line of (await readFile(join(directory, 'SHA256SUMS.txt'), 'utf8')).trim().split('\n')) {
  const match = /^([a-f0-9]{64})  ([A-Za-z0-9._-]+)$/.exec(line)
  assert.ok(match, 'Invalid checksum entry')
  assert.equal(digest(await readFile(join(directory, match[2]))), match[1], match[2])
}
const agent = inspectArchive(await readFile(join(directory, manifest.agentPackage)))
assert.equal(agent.manifest.version, manifest.version)
assert.equal(agent.files.get('package/payload/VERSION').toString().trim(), manifest.version)
for (const name of ['DATA_CAPABILITIES.md', 'QUICKSTART.md', 'AGENT_INSTALL.md']) assert.ok(agent.files.has(`package/${name}`), name)
for (const name of agent.files.keys()) assert.ok(!/(?:computer_use\.py|browser_skill\.py|computer-use\.mjs)$/.test(name), name)
await verifyPackage(join(directory, manifest.harnessPackage))
const check = spawnSync('python3', ['-B', '-c', `
import hashlib,json,pathlib,sys,zipfile
folder=pathlib.Path(sys.argv[1]); manifest=json.loads((folder/'PACKAGE.json').read_text())
def sha(data):return hashlib.sha256(data).hexdigest()
for key in ('sourcePackage','completePackage','setupFile'):
 with zipfile.ZipFile(folder/manifest[key]) as archive:
  names=archive.namelist()
  assert len(names)==len(set(names))
  assert all(not name.startswith('/') and '..' not in pathlib.PurePosixPath(name).parts and chr(92) not in name for name in names)
  assert all(not ((info.external_attr>>16)&0o170000)==0o120000 for info in archive.infolist())
  assert all(not set(pathlib.PurePosixPath(name).parts).intersection({'.git','.superpowers','node_modules','chrome-profile','browser-profile','__pycache__','.DS_Store'}) for name in names)
  prefix=names[0].split('/')[0]+'/'
  if key=='sourcePackage':
   receipt=json.loads(archive.read(prefix+'SOURCE_MANIFEST.json'))
   assert receipt['sourceTreeSha256']==manifest['sourceTreeSha256']
   for name,expected in receipt['files'].items():assert sha(archive.read(prefix+name))==expected,name
   assert archive.read(prefix+'VERSION').decode().strip()==manifest['version']
  elif key=='completePackage':
   for line in archive.read(prefix+'SHA256SUMS.txt').decode().splitlines():
    expected,name=line.split('  ',1);assert sha(archive.read(prefix+name))==expected,name
   for name in ('DATA_CAPABILITIES.md','QUICKSTART.md','VALIDATION.json','examples/posts.sample.json'):assert prefix+name in names
  else:
   for name in ('DATA_CAPABILITIES.md','QUICKSTART.md','AGENT_INSTALL.md','examples/posts.sample.json'):assert prefix+name in names
   assert sha(archive.read(prefix+manifest['agentPackage']))==manifest['packageSha256']
print('All ZIP entries, source file hashes, embedded component hashes and guides verified.')
`, directory], { encoding: 'utf8', shell: false })
if (check.error || check.status !== 0) throw new Error(`distribution_zip_verification_failed:${check.stderr}`)
console.log(JSON.stringify({ status: 'passed', version: manifest.version, sourceFiles: manifest.sourceFileCount, sourceTreeSha256: manifest.sourceTreeSha256, packageSha256: manifest.packageSha256, setupSha256: manifest.setupSha256, archiveChecks: check.stdout.trim() }, null, 2))
