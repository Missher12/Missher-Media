#!/usr/bin/env node
import { homedir } from 'node:os'
import { join } from 'node:path'
import { parseArgs } from 'node:util'
import { pathToFileURL } from 'node:url'
import { createSetupTool, normalizePluginConfig } from '../lib/index.js'

export async function withSetupSignals(operation) {
  const controller = new AbortController()
  let exitCode = 0
  const interrupt = () => { exitCode ||= 130; controller.abort() }
  const terminate = () => { exitCode ||= 143; controller.abort() }
  process.on('SIGINT', interrupt)
  process.on('SIGTERM', terminate)
  try { return { result: await operation(controller.signal), exitCode } }
  finally { process.off('SIGINT', interrupt); process.off('SIGTERM', terminate) }
}

async function main() {
  const argv = process.argv.slice(2)
  const { values, positionals } = parseArgs({ args: argv[0] === '--' ? argv.slice(1) : argv, allowPositionals: true, options: {
    profile: { type: 'string' }, file: { type: 'string' }, 'import-id': { type: 'string' }, rows: { type: 'string' }, 'confirm-open': { type: 'boolean' }, help: { type: 'boolean' },
  } })
  if (values.help) {
    process.stdout.write('Offline setup: status | template | import --file /absolute/creators.xlsx | activate --import-id <ID> --rows 1,3\nBrowser setup after selecting creators: browser-check | browser-open --confirm-open\nOpening uses a separate AI Chrome profile and a local login guide. Login is manual; no collection starts.\nOptional: --profile /absolute/private/profile.json\n')
  } else {
    const config = normalizePluginConfig(values.profile ? { profilePath: values.profile } : {}, process.env.DSH_HOME || join(homedir(), '.dsh'))
    const args = { action: positionals.length === 1 ? positionals[0] : '' }
    if (values.file !== undefined) args.input_path = values.file
    if (values['import-id'] !== undefined) args.import_id = values['import-id']
    if (values.rows !== undefined) args.rows = values.rows.split(',').map(value => /^\d+$/.test(value) ? Number(value) : null)
    if (values['confirm-open'] !== undefined) args.confirm_open = values['confirm-open']
    const { result, exitCode } = await withSetupSignals(signal => createSetupTool(config).execute(args, { signal }))
    process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
    process.exitCode = exitCode || (result.status === 'failed' ? 1 : 0)
  }
}

if (process.argv[1] && pathToFileURL(process.argv[1]).href === import.meta.url) await main()
