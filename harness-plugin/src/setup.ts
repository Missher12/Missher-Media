import { createHash, randomBytes } from 'node:crypto'
import { lstat, rename, rmdir, unlink } from 'node:fs/promises'
import { dirname, extname, join } from 'node:path'
import type { ToolDefinition } from '@deepseek-ai/dsh-tools'
import { normalizeTarget, PLATFORMS, targetIdentity, type CollectTarget, type PluginConfig } from './config.js'
import { checkBrowser, openAiBrowser, type BrowserSetupDependencies, type BrowserSetupValue } from './browser-setup.js'
import { buildCreatorTemplates, parseCreatorList, type Creator } from './creator-list.js'
import { checkPath, isMissing, jsonObject, parseProfileSnapshot, privateDirectory, readBoundedFile, readProfileSnapshot, writePrivateFile, type ProfileSnapshot } from './private-config.js'

interface SetupValue {
  status: 'ok' | 'needs-setup' | 'failed'
  summary: string
  artifactPath: string
  metadataPath: string
  importId: string
  rowCount: number
  configuredPlatforms: string
  activePlatforms: string
  browserStatus: 'not-checked' | BrowserSetupValue['browserStatus']
  browserIdentity: BrowserSetupValue['browserIdentity']
  openPlatforms: string
  missingPlatforms: string
  loginStatus: 'not-checked'
}
const empty = (): SetupValue => ({ status: 'ok', summary: '', artifactPath: '', metadataPath: '', importId: '', rowCount: 0, configuredPlatforms: '', activePlatforms: '', browserStatus: 'not-checked', browserIdentity: 'not-checked', openPlatforms: '', missingPlatforms: '', loginStatus: 'not-checked' })
const id = () => randomBytes(16).toString('hex')
const csvCell = (value: string) => `"${value.replaceAll('"', '""')}"`
const markdown = (value: string) => value.replace(/\r\n|[\r\n]/g, ' ↵ ').replace(/\t/g, ' ').replace(/[\\`*{}[\]<>()_!#|]/g, '\\$&')
const digest = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex')
const previewText = (creators: Creator[]) => ['# 博主名单预览', '', '这是导入文件中的资料。请选择本次行号；同一平台可以选择多位博主，每次选择都形成独立目标。', '', '| 行号 | 平台 | 博主名称 | 主页 |', '| --- | --- | --- | --- |',
  ...creators.map((creator, index) => `| ${index + 1} | ${creator.platform} | ${markdown(creator.name)} | ${markdown(creator.homepage)} |`), ''].join('\n')

async function readImport(path: string, expectedDigest: string): Promise<Creator[]> {
  const bytes = await readBoundedFile(path, 1024 * 1024)
  if (digest(bytes) !== expectedDigest) throw new Error('setup_import_changed')
  const saved = jsonObject(bytes)
  if (saved.schema !== 1 || !Array.isArray(saved.creators) || saved.creators.length < 1 || saved.creators.length > 200) throw new Error('setup_import_invalid')
  const original = saved.creators as unknown[]
  for (const item of original) {
    if (item === null || typeof item !== 'object' || Array.isArray(item)
      || Object.keys(item).sort().join(',') !== 'homepage,name,nativeId,platform'
      || Object.values(item).some(value => typeof value !== 'string')) throw new Error('setup_import_invalid')
  }
  const creators = original as Creator[]
  // Validate saved imports again; an edited nativeId cannot override the reviewed homepage identity.
  const csv = ['platform,creator_name,homepage_url', ...creators.map(item => [item.platform, item.name, item.homepage].map(csvCell).join(','))].join('\n')
  const validated = await parseCreatorList(Buffer.from(csv), 'csv')
  if (validated.some((item, index) => ['platform', 'name', 'homepage', 'nativeId'].some(key => item[key as keyof Creator] !== creators[index]![key as keyof Creator]))) throw new Error('setup_import_invalid')
  const preview = await readBoundedFile(join(dirname(path), 'preview.md'), 1024 * 1024)
  if (preview.toString('utf8') !== previewText(validated)) throw new Error('setup_preview_changed')
  return validated
}

async function withProfileLock<T>(config: PluginConfig, setupRoot: string, operation: (prior: ProfileSnapshot | undefined) => Promise<T>): Promise<T> {
  await privateDirectory(dirname(config.profilePath))
  await privateDirectory(setupRoot)
  const lockPath = join(setupRoot, 'activate.lock')
  try { await writePrivateFile(lockPath, `${id()}\n`) } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'EEXIST') throw new Error('setup_busy')
    throw error
  }
  const lock = await lstat(lockPath)
  try { return await operation(await readProfileSnapshot(config.profilePath)) }
  finally {
    const current = await lstat(lockPath)
    if (lock.dev === current.dev && lock.ino === current.ino) await unlink(lockPath)
  }
}

async function saveProfile(config: PluginConfig, setupRoot: string, value: Record<string, unknown>, prior: ProfileSnapshot | undefined): Promise<void> {
  const next = Buffer.from(`${JSON.stringify(value, null, 2)}\n`)
  if (next.length > 256 * 1024) throw new Error('setup_file_too_large')
  parseProfileSnapshot(next)
  const nonce = id()
  if (prior !== undefined) {
    const backupRoot = join(setupRoot, 'backups')
    await privateDirectory(backupRoot)
    await writePrivateFile(join(backupRoot, `profile-${nonce}.json`), prior.bytes)
  }
  const temporary = join(dirname(config.profilePath), `.profile-${nonce}.tmp`)
  await writePrivateFile(temporary, next)
  try {
    const current = await readProfileSnapshot(config.profilePath)
    if (prior === undefined ? current !== undefined : current === undefined || !prior.bytes.equals(current.bytes)) throw new Error('setup_profile_changed')
    await checkPath(config.profilePath)
    await rename(temporary, config.profilePath)
  } finally { await unlink(temporary).catch(error => { if (!isMissing(error)) throw error }) }
}

/** Convert the reviewed rows and explicit targets into the versioned plan targets. */
function activationTargets(
  creators: Creator[],
  explicit: CollectTarget[],
): CollectTarget[] {
  const targets: CollectTarget[] = creators.map(creator => ({
    platform: creator.platform,
    mode: 'creator',
    uid: creator.nativeId,
    ...(creator.name ? { label: creator.name } : {}),
    ...(creator.homepage ? { homepage: creator.homepage } : {}),
  }))
  const identities = new Set(targets.map(targetIdentity))
  for (const target of explicit) {
    const identity = targetIdentity(target)
    if (identities.has(identity)) throw new Error('setup_selection_ambiguous')
    identities.add(identity)
    targets.push(target)
  }
  return targets
}

async function activate(
  config: PluginConfig,
  setupRoot: string,
  creators: Creator[],
  explicit: CollectTarget[] = [],
): Promise<SetupValue> {
  return withProfileLock(config, setupRoot, async prior => {
    const value = prior?.value ?? {}
    const targets = activationTargets(creators, explicit)
    if (targets.length === 0) throw new Error('setup_selection_invalid')
    // `platform_uids` and `creator_targets` are the version 1 compatibility view.
    // They cannot express several accounts on one platform, so they keep the
    // first target per platform while `targets` stays authoritative.
    const platformUids = { ...(value.platform_uids as Record<string, unknown> | undefined) }
    const priorCreators = value.creator_targets
    if (priorCreators !== undefined && (priorCreators === null || typeof priorCreators !== 'object' || Array.isArray(priorCreators))) throw new Error('profile_targets_invalid')
    const creatorTargets = { ...(priorCreators as Record<string, unknown> | undefined) }
    const decorated: CollectTarget[] = []
    for (const target of targets) {
      const creator = target.uid === undefined
        ? undefined
        : creators.find(item => item.platform === target.platform && item.nativeId === target.uid)
      decorated.push(creator === undefined ? target : { ...target, label: creator.name, homepage: creator.homepage })
      // The version 1 mirror keeps one account per platform; the author decorations
      // stay keyed by author id so several accounts remain distinguishable.
      if (target.uid !== undefined) {
        if (platformUids[target.platform] === undefined) platformUids[target.platform] = target.uid
        creatorTargets[`${target.platform}:${target.uid}`] = {
          ...(creator?.name === undefined ? (target.label === undefined ? {} : { name: target.label }) : { name: creator.name }),
          ...(creator?.homepage === undefined ? (target.homepage === undefined ? {} : { homepage: target.homepage }) : { homepage: creator.homepage }),
        }
      }
      if (creator !== undefined) creatorTargets[creator.platform] = { name: creator.name, homepage: creator.homepage }
    }
    const activePlatforms = PLATFORMS.filter(platform => decorated.some(item => item.platform === platform))
    const next = {
      ...value,
      targets: decorated,
      platform_uids: platformUids,
      creator_targets: creatorTargets,
      active_platforms: activePlatforms,
    }
    await saveProfile(config, setupRoot, next, prior)
    // Re-read what was actually written so the reported state is the saved state,
    // including platforms configured by an earlier selection.
    const saved = parseProfileSnapshot(Buffer.from(`${JSON.stringify(next, null, 2)}\n`))
    return { ...empty(), summary: `已选择 ${decorated.length} 个采集目标，其中 ${creators.length} 位来自名单；同一平台可以有多个帐号。可按需打开 AI 采集浏览器并自行登录，明确本次条数和导航范围后再采集。`,
      configuredPlatforms: saved.available.join(','),
      activePlatforms: saved.active.join(','), rowCount: decorated.length }
  })
}

/** Offline onboarding works before Python, a CDP endpoint, or any platform session exists. */
export function createSetupTool(config: PluginConfig, browserDependencies: BrowserSetupDependencies = {}): ToolDefinition {
  const setupRoot = join(dirname(config.profilePath), 'setup')
  return {
    name: 'media_missher_setup',
    description: 'Prepare a new Media@Missher device offline. status inspects local target readiness; template generates an empty Excel/CSV; import parses a user-provided local file and returns a private preview with row numbers and an import ID; activate selects explicit preview row numbers plus optional explicit targets and backs up the previous profile. Several accounts on the same platform are allowed in one selection. Preview before activating. Names are display labels; a full official homepage or a native identifier identifies a creator, and a nickname alone is never resolved to an identity. Selecting a creator target is not switching the logged-in account: this tool never switches accounts. browser-check explicitly checks local CDP and selected platform pages, never login credentials. browser-open with confirm_open=true opens an isolated AI browser and local login guide only when the user asks to open it; it backs up and updates the local CDP setting. Never call browser-open automatically from status/import/activate/collect. Never invent targets, resolve names online, auto-collect, install a runtime, automate login or change risk state.',
    parameters: {
      type: 'object', additionalProperties: false, required: ['action'],
      properties: {
        action: { type: 'string', enum: ['status', 'template', 'import', 'activate', 'browser-check', 'browser-open'] },
        confirm_open: { type: 'boolean', description: 'Must be true only for an explicit user request to open the separate AI collection browser. Opening a browser does not authorize collection or automatic login.' },
        input_path: { type: 'string', description: 'Absolute path of the user-provided .csv or .xlsx for import.' },
        import_id: { type: 'string', description: 'Exact import ID returned with the reviewed preview.' },
        rows: { type: 'array', items: { type: 'integer' }, description: 'Explicit one-based preview row numbers for this selection. Several rows may share one platform; up to 200 rows.' },
        targets: { type: 'array', items: { type: 'object' }, description: 'Optional explicit targets that are not in the roster, e.g. {platform:"weibo",mode:"topic",topic:"旅行",topic_kind:"topic"} or {platform:"x",mode:"search",keyword:"ai",sort:"latest"}. A topic target is Weibo-only and needs an explicit topic_kind.' },
      },
    },
    output: {
      schema: { type: 'object', additionalProperties: false, required: Object.keys(empty()), properties: {
        status: { type: 'string', enum: ['ok', 'needs-setup', 'failed'] }, summary: { type: 'string' }, artifactPath: { type: 'string' }, metadataPath: { type: 'string' }, importId: { type: 'string' }, rowCount: { type: 'integer' }, configuredPlatforms: { type: 'string' }, activePlatforms: { type: 'string' }, browserStatus: { type: 'string', enum: ['not-checked', 'ready', 'not-running', 'missing-chrome', 'busy', 'starting'] }, browserIdentity: { type: 'string', enum: ['not-checked', 'ai-dedicated', 'configured-external'] }, openPlatforms: { type: 'string' }, missingPlatforms: { type: 'string' }, loginStatus: { type: 'string', enum: ['not-checked'] },
      } },
      render: (_args, raw) => {
        const value = raw as unknown as SetupValue
        const browserGuidance: Record<string, string> = {
          setup_browser_open_not_confirmed: '只有用户明确要求打开 AI 采集浏览器时，才传入 confirm_open=true。',
          setup_browser_port_busy: '本机 9223 端口属于其他会话或未能验证。保留现有进程，请用户检查；不要自动关闭它或换浏览器继续采集。',
          setup_browser_profile_busy: '专用浏览器资料目录仍在使用。请用户自行检查窗口，本次不重复启动。',
          setup_browser_environment_override: 'MEDIA_MISSHER_CDP_URL 覆盖了专用浏览器端口。请核实该本地设置；本次未改动它。',
          setup_browser_endpoint_unsupported: '浏览器引导只支持本机 HTTP CDP 端口，既有其他连接配置保持原样。',
          setup_browser_directory_unrecognized: '预定浏览器目录已有未知内容，本次保留原目录。请检查目录归属后再准备。',
          setup_browser_launch_failed: 'Chrome 启动失败。请检查系统提示或 Chrome 安装；名单和原连接配置仍保留。',
          setup_browser_platform_unsupported: 'AI 浏览器支持 macOS/Linux；Windows 请使用 WSL2 入口。',
          setup_browser_graphical_session_required: '请在 Linux 图形桌面或 WSLg 会话中打开浏览器。不要改成无头模式或开放远程 CDP。',
          setup_browser_root_unsupported: '请使用普通 Linux 用户运行浏览器，不要关闭 Chrome 沙箱。',
        }
        const guidance = value.status === 'failed' && value.summary.startsWith('creator_list_')
          ? '请按空模板填写平台、博主名称、完整主页三列；保留普通单元格，不添加公式、合并或嵌入对象。'
          : browserGuidance[value.summary] ?? ''
        return [{ type: 'text', text: [value.summary, guidance, value.activePlatforms ? `本次平台：${value.activePlatforms}` : '', value.importId ? `Import ID: ${value.importId}` : '', value.artifactPath, value.metadataPath].filter(Boolean).join('\n') }]
      },
    },
    timeoutMs: 30000,
    presentCall: () => ({ card: 'generic', title: 'Media@Missher device setup', kind: 'search' }),
    async execute(raw, exec): Promise<SetupValue> {
      try {
        exec.signal?.throwIfAborted()
        if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('setup_arguments_invalid')
        const args = raw as Record<string, unknown>
        const allowed: Record<string, string[]> = { status: ['action'], template: ['action'], import: ['action', 'input_path'], activate: ['action', 'import_id', 'rows', 'targets'], 'browser-check': ['action'], 'browser-open': ['action', 'confirm_open'] }
        if (typeof args.action !== 'string' || !Object.hasOwn(allowed, args.action) || Object.keys(args).some(key => !allowed[args.action as string]!.includes(key))) throw new Error('setup_arguments_invalid')
        if (args.action === 'browser-open' && args.confirm_open !== true) throw new Error('setup_browser_open_not_confirmed')
        if (args.action === 'browser-check' || args.action === 'browser-open') {
          const profile = await readProfileSnapshot(config.profilePath)
          const needsTargets = () => ({ ...empty(), status: 'needs-setup' as const, summary: '请先导入名单并选择本次博主，再准备 AI 采集浏览器。' })
          if (!profile?.active.length) return needsTargets()
          const signal = exec.signal ?? new AbortController().signal
          if (args.action === 'browser-check') return { ...empty(), configuredPlatforms: profile.available.join(','), activePlatforms: profile.active.join(','), ...await checkBrowser(config, profile.value, profile.active, signal, browserDependencies) }
          return await withProfileLock(config, setupRoot, async current => {
            if (!current?.active.length) return needsTargets()
            signal.throwIfAborted()
            const { endpoint, ...result } = await openAiBrowser(config, signal, browserDependencies)
            signal.throwIfAborted()
            if (endpoint !== undefined && current.value.cdp_url !== endpoint) await saveProfile(config, setupRoot, { ...current.value, cdp_url: endpoint }, current)
            return { ...empty(), configuredPlatforms: current.available.join(','), activePlatforms: current.active.join(','), ...result }
          })
        }
        if (args.action === 'status') {
          const profile = await readProfileSnapshot(config.profilePath)
          return { ...empty(), status: profile?.active.length ? 'ok' : 'needs-setup',
            configuredPlatforms: profile?.available.join(',') ?? '', activePlatforms: profile?.active.join(',') ?? '',
            summary: profile?.active.length ? '本次博主已配置。浏览器及登录状态尚未检查；采集仅连接已有 CDP，不会自动打开 Chrome。' : '请生成 Excel/CSV 模板，导入博主名称和完整主页，预览后选择本次目标。' }
        }
        if (args.action === 'template') {
          const templates = await buildCreatorTemplates()
          exec.signal?.throwIfAborted()
          await privateDirectory(setupRoot)
          const prefix = join(setupRoot, `creators-template-${id()}`)
          await writePrivateFile(`${prefix}.xlsx`, templates.xlsx)
          await writePrivateFile(`${prefix}.csv`, templates.csv)
          return { ...empty(), summary: '填写平台、博主名称、完整主页链接后导入；模板不含可采集目标。', artifactPath: `${prefix}.xlsx`, metadataPath: `${prefix}.csv` }
        }
        if (args.action === 'import') {
          if (typeof args.input_path !== 'string') throw new Error('setup_arguments_invalid')
          const extension = extname(args.input_path).toLowerCase()
          if (extension !== '.csv' && extension !== '.xlsx') throw new Error('setup_format_invalid')
          const bytes = await readBoundedFile(args.input_path, 2 * 1024 * 1024, false)
          const creators = await parseCreatorList(bytes, extension === '.csv' ? 'csv' : 'xlsx')
          exec.signal?.throwIfAborted()
          const saved = Buffer.from(`${JSON.stringify({ schema: 1, creators }, null, 2)}\n`)
          const importId = `import-${id()}-${digest(saved)}`
          const target = join(setupRoot, importId)
          const pending = join(setupRoot, `.pending-${importId}`)
          await privateDirectory(pending)
          let moved = false
          try {
            await writePrivateFile(join(pending, 'creators.json'), saved)
            await writePrivateFile(join(pending, 'preview.md'), previewText(creators))
            await rename(pending, target)
            moved = true
          } finally {
            if (!moved) {
              for (const name of ['creators.json', 'preview.md']) await unlink(join(pending, name)).catch(error => { if (!isMissing(error)) throw error })
              await rmdir(pending)
            }
          }
          return { ...empty(), summary: `已导入 ${creators.length} 位博主。请查看预览并明确选择行号；尚未修改采集目标。`, importId, rowCount: creators.length, artifactPath: join(target, 'preview.md'), metadataPath: join(target, 'creators.json') }
        }
        if (typeof args.import_id !== 'string' || !/^import-[a-f0-9]{32}-[a-f0-9]{64}$/.test(args.import_id)) throw new Error('setup_selection_invalid')
        const rawRows = args.rows ?? []
        if (!Array.isArray(rawRows) || rawRows.length > 200
          || rawRows.some(row => !Number.isInteger(row) || row < 1 || row > 200) || new Set(rawRows).size !== rawRows.length) throw new Error('setup_selection_invalid')
        const rawTargets = args.targets ?? []
        if (!Array.isArray(rawTargets) || rawTargets.length > 200) throw new Error('setup_selection_invalid')
        if (rawRows.length === 0 && rawTargets.length === 0) throw new Error('setup_selection_invalid')
        const explicit = (rawTargets as unknown[]).map(normalizeTarget)
        const creators = await readImport(join(setupRoot, args.import_id, 'creators.json'), args.import_id.slice(-64))
        const selected = (rawRows as number[]).map(row => creators[row - 1])
        if (selected.some(creator => creator === undefined)) throw new Error('setup_selection_invalid')
        const rows = selected as Creator[]
        const seenRows = new Set(rows.map(creator => `${creator.platform}:${creator.nativeId}`))
        if (seenRows.size !== rows.length) throw new Error('setup_selection_ambiguous')
        exec.signal?.throwIfAborted()
        return await activate(config, setupRoot, rows, explicit)
      } catch (error) {
        if (exec.signal?.aborted) return { ...empty(), status: 'failed', summary: 'setup_cancelled' }
        const message = (error as Error).message
        return { ...empty(), status: 'failed', summary: /^(?:setup|creator_list|profile)_[a-z_]+(?::row_[0-9]+)?$/.test(message) ? message : 'setup_failed' }
      }
    },
  }
}
