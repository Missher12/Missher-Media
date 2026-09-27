import { spawn } from 'node:child_process'
import { mkdtemp, readdir, realpath, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { expect, it } from 'vitest'

it.each(['SIGINT', 'SIGTERM'] as const)('waits for CLI cleanup after %s', async signal => {
  const root = await realpath(await mkdtemp(join(tmpdir(), 'media-cli-cancel-')))
  const script = new URL('../scripts/setup-device.mjs', import.meta.url).href
  const source = `
    import { writeFile, unlink } from 'node:fs/promises';
    import { withSetupSignals } from ${JSON.stringify(script)};
    const lock = ${JSON.stringify(join(root, 'activate.lock'))};
    const { result, exitCode } = await withSetupSignals(async signal => {
      await writeFile(lock, 'owned');
      process.stdout.write('ready\\n');
      try { await new Promise(resolve => { const timer = setInterval(() => {}, 1000); signal.addEventListener('abort', () => { clearInterval(timer); resolve(); }, { once: true }); }); return 'cancelled'; }
      finally { await unlink(lock); }
    });
    process.stdout.write(result); process.exitCode = exitCode;
  `
  try {
    const result = await new Promise<{ code: number | null; signal: string | null; output: string }>((resolve, reject) => {
      const child = spawn(process.execPath, ['--input-type=module', '-e', source], { stdio: ['ignore', 'pipe', 'pipe'] })
      let output = ''; let sent = false
      const timer = setTimeout(() => child.kill('SIGKILL'), 10_000)
      child.stdout.on('data', chunk => { output += chunk.toString(); if (!sent && output.includes('ready\n')) { sent = true; child.kill(signal) } })
      child.once('error', error => { clearTimeout(timer); reject(error) })
      child.once('close', (code, endSignal) => { clearTimeout(timer); resolve({ code, signal: endSignal, output }) })
    })
    expect(result).toEqual({ code: signal === 'SIGINT' ? 130 : 143, signal: null, output: 'ready\ncancelled' })
    expect(await readdir(root)).toEqual([])
  } finally { await rm(root, { recursive: true, force: true }) }
})
