import assert from 'node:assert/strict'
import { test } from 'node:test'
import {
  BACKENDS, EXPORT_FORMATS, EXPORT_RECORD_KINDS, MAX_TARGETS, PLATFORMS, TARGET_ERROR_CODES, TARGET_MODES, TargetError,
  normalizeExportSelection, normalizeTarget, normalizeTargets, parseCountMode, resolveBackend, targetIdentity,
} from '../src/targets.mjs'

/** One reachable failure per fixed code; the table is the completeness proof. */
const FAILURES = [
  ['backend-retired-browserskill', () => resolveBackend('browserskill')],
  ['backend-retired-computer-use', () => resolveBackend('computer_use')],
  ['backend_auto_unsupported', () => resolveBackend('auto', undefined)],
  ['backend_invalid', () => resolveBackend('playwright', undefined)],
  ['count_mode_invalid', () => parseCountMode('endless')],
  ['export_arguments_invalid', () => normalizeExportSelection({ run_id: 'run-a', runId: 'run-a' })],
  ['export_field_groups_invalid', () => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], fieldGroups: ['engagement', 'engagement'] })],
  ['export_fields_invalid', () => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], fields: ['tweet_id', ' '] })],
  ['export_file_name_invalid', () => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], fileName: 'nested/run.xlsx' })],
  ['export_format_invalid', () => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], format: 'pdf' })],
  ['export_overwrite_invalid', () => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], overwrite: 'yes' })],
  ['export_platforms_invalid', () => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], platforms: ['myspace'] })],
  ['export_record_kinds_invalid', () => normalizeExportSelection({ runId: 'run-a', recordKinds: [] })],
  ['export_targets_invalid', () => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], targets: ['x:creator:1', 'x:creator:1'] })],
  ['export_topics_invalid', () => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], topics: ['旅行', '旅行'] })],
  ['run_id_invalid', () => normalizeExportSelection({ runId: '../etc/passwd', recordKinds: ['posts'] })],
  ['target_handle_invalid', () => normalizeTarget({ platform: 'x', handle: 'not a handle' })],
  ['target_homepage_invalid', () => normalizeTarget({ platform: 'x', homepage: 'http://x.com/somebody' })],
  ['target_identity_missing', () => normalizeTarget({ platform: 'x', label: 'Somebody' })],
  ['target_invalid', () => normalizeTarget({ platform: 'x', uid: '12345', identity: 'x:creator:1' })],
  ['target_keyword_invalid', () => normalizeTarget({ platform: 'x', mode: 'search', keyword: 'ai\nfuture' })],
  ['target_keyword_missing', () => normalizeTarget({ platform: 'x', mode: 'search' })],
  ['target_label_invalid', () => normalizeTarget({ platform: 'x', uid: '12345', label: 'x'.repeat(257) })],
  ['target_mode_invalid', () => normalizeTarget({ platform: 'x', mode: 'followers', uid: '12345' })],
  ['target_platform_invalid', () => normalizeTarget({ platform: 'youtube', uid: '12345' })],
  ['target_sort_invalid', () => normalizeTarget({ platform: 'x', mode: 'search', keyword: 'ai', sort: 'newest' })],
  ['target_topic_invalid', () => normalizeTarget({ platform: 'weibo', mode: 'topic', topic: '旅行\u0007' })],
  ['target_topic_kind_invalid', () => normalizeTarget({ platform: 'weibo', mode: 'topic', topic: '旅行', topicKind: 'mega' })],
  ['target_topic_missing', () => normalizeTarget({ platform: 'weibo', mode: 'topic' })],
  ['target_topic_platform_invalid', () => normalizeTarget({ platform: 'x', mode: 'topic', topic: '旅行' })],
  ['target_uid_invalid', () => normalizeTarget({ platform: 'bilibili', uid: '12a45' })],
  ['targets_duplicate', () => normalizeTargets([{ platform: 'x', uid: '12345' }, { platform: 'x', uid: '12345' }])],
  ['targets_invalid', () => normalizeTargets(Array.from({ length: MAX_TARGETS + 1 }, (unused, index) => ({ platform: 'x', uid: String(index + 1) })))],
]

test('every fixed code is reachable, sorted and complete', () => {
  assert.deepEqual([...TARGET_ERROR_CODES], [...TARGET_ERROR_CODES].sort())
  assert.equal(new Set(TARGET_ERROR_CODES).size, TARGET_ERROR_CODES.length)
  assert.deepEqual([...new Set(FAILURES.map(([code]) => code))].sort(), [...TARGET_ERROR_CODES].sort())
})

test('failures are TargetError with a fixed code and never echo the rejected value', () => {
  for (const [code, run] of FAILURES) {
    assert.throws(run, error => {
      assert.ok(error instanceof TargetError, `${code} must be a TargetError`)
      assert.equal(error.code, code)
      assert.equal(error.message, code)
      return true
    }, code)
  }
  for (const [secret, run] of [
    ['private handle', () => normalizeTarget({ platform: 'x', handle: 'private handle' })],
    ['PRIVATE-SECRET', () => normalizeTarget({ platform: 'weibo', mode: 'topic', topic: 'PRIVATE\u0001SECRET' })],
    ['/Users/private', () => normalizeExportSelection({ runId: '/Users/private', recordKinds: ['posts'] })],
    ['PRIVATE.csv', () => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], fileName: 'a/PRIVATE.csv' })],
  ]) {
    assert.throws(run, error => {
      assert.match(error.message, /^[a-z0-9_]+$/u)
      assert.doesNotMatch(error.message, new RegExp(secret, 'u'))
      return true
    }, secret)
  }
})

test('the five platforms, three task modes and sole CDP backend are exported in order', () => {
  assert.deepEqual(PLATFORMS, ['bilibili', 'xhs', 'douyin', 'weibo', 'x'])
  assert.deepEqual(TARGET_MODES, ['creator', 'search', 'topic'])
  assert.deepEqual(BACKENDS, ['cdp'])
  assert.deepEqual(EXPORT_RECORD_KINDS, ['posts', 'topic_participants', 'user_profiles'])
  assert.deepEqual(EXPORT_FORMATS, ['xlsx', 'csv', 'json', 'jsonl', 'sqlite'])
})

test('creator, search and topic identities use the documented shapes', () => {
  assert.equal(targetIdentity(normalizeTarget({ platform: 'bilibili', mode: 'creator', uid: '12345' })), 'bilibili:creator:12345')
  assert.equal(targetIdentity(normalizeTarget({ platform: 'weibo', mode: 'creator', handle: '@Somebody' })), 'weibo:creator:Somebody')
  assert.equal(targetIdentity(normalizeTarget({ platform: 'x', mode: 'creator', homepage: 'https://x.com/somebody' })), 'x:creator:https://x.com/somebody')
  assert.equal(targetIdentity(normalizeTarget({ platform: 'x', mode: 'creator', uid: '12345', handle: 'Somebody', homepage: 'https://x.com/somebody', label: 'Display' })), 'x:creator:12345')
  assert.equal(targetIdentity(normalizeTarget({ platform: 'x', mode: 'search', keyword: 'ai' })), 'x:search:latest:ai')
  assert.equal(targetIdentity(normalizeTarget({ platform: 'x', mode: 'search', keyword: 'ai', sort: 'top' })), 'x:search:top:ai')
  assert.equal(targetIdentity(normalizeTarget({ platform: 'weibo', mode: 'topic', topic: '旅行' })), 'weibo:topic:topic:旅行')
  assert.equal(targetIdentity(normalizeTarget({ platform: 'weibo', mode: 'topic', topic: '旅行超话', topicKind: 'super' })), 'weibo:topic:super:旅行超话')
  assert.throws(() => targetIdentity(null), error => error.code === 'target_invalid')
  assert.throws(() => targetIdentity({ platform: 'youtube', mode: 'creator', uid: '1' }), error => error.code === 'target_platform_invalid')
  assert.throws(() => targetIdentity({ platform: 'x', mode: 'followers' }), error => error.code === 'target_mode_invalid')
})

test('a creator target keeps its native fields, normalizes the handle and defaults a topic kind', () => {
  const creator = normalizeTarget({ platform: 'douyin', mode: 'creator', uid: '0012345', label: '  昵称  ' })
  assert.deepEqual(creator, { platform: 'douyin', mode: 'creator', label: '昵称', uid: '0012345' })
  assert.deepEqual(normalizeTarget({ platform: 'x', handle: '@Somebody' }), { platform: 'x', mode: 'creator', handle: 'somebody' })
  assert.equal(normalizeTarget({ platform: 'xhs', uid: 'a'.repeat(24) }).uid, 'a'.repeat(24))
  assert.equal(normalizeTarget({ platform: 'douyin', uid: 'MS4wLjABAAAA_fixture' }).uid, 'MS4wLjABAAAA_fixture')
  assert.throws(() => normalizeTarget({ platform: 'x', handle: 'a'.repeat(16) }), error => error.code === 'target_handle_invalid')
  assert.deepEqual(normalizeTarget({ platform: 'x', mode: 'creator', uid: '1', homepage: 'https://x.com/somebody' }), { platform: 'x', mode: 'creator', uid: '1', homepage: 'https://x.com/somebody' })
  assert.deepEqual(normalizeTarget({ platform: 'weibo', mode: 'topic', topic: ' 旅行 ' }), { platform: 'weibo', mode: 'topic', topic: '旅行', topicKind: 'topic' })
  assert.deepEqual(normalizeTarget({ platform: 'weibo', mode: 'topic', topic: '#旅行#', topicKind: 'super' }).topicKind, 'super')
})

test('fields that do not belong to the selected mode are rejected instead of dropped', () => {
  for (const [input, code] of [
    [{ platform: 'x', mode: 'creator', uid: '1', keyword: 'ai' }, 'target_keyword_invalid'],
    [{ platform: 'x', mode: 'creator', uid: '1', topic: '旅行' }, 'target_topic_invalid'],
    [{ platform: 'x', mode: 'creator', uid: '1', sort: 'top' }, 'target_sort_invalid'],
    [{ platform: 'weibo', mode: 'creator', uid: '1', topicKind: 'super' }, 'target_topic_kind_invalid'],
    [{ platform: 'x', mode: 'search', keyword: 'ai', uid: '1' }, 'target_uid_invalid'],
    [{ platform: 'weibo', mode: 'topic', topic: '旅行', handle: 'Somebody' }, 'target_handle_invalid'],
  ]) assert.throws(() => normalizeTarget(input), error => error.code === code, code)
})

test('normalizeTargets keeps several accounts on one platform and rejects duplicate identities', () => {
  const many = [
    { platform: 'bilibili', mode: 'creator', uid: '1' },
    { platform: 'bilibili', mode: 'creator', uid: '2' },
    { platform: 'bilibili', mode: 'creator', uid: '3' },
    { platform: 'bilibili', mode: 'creator', uid: '4' },
    { platform: 'bilibili', mode: 'creator', uid: '5' },
    { platform: 'x', mode: 'creator', handle: 'Somebody' },
    { platform: 'weibo', mode: 'topic', topic: '旅行' },
    { platform: 'x', mode: 'search', keyword: 'ai' },
  ]
  assert.equal(normalizeTargets(many).length, many.length)
  assert.deepEqual(normalizeTargets([]), [])
  const atLimit = Array.from({ length: MAX_TARGETS }, (unused, index) => ({ platform: 'x', mode: 'creator', uid: String(index + 1) }))
  assert.equal(normalizeTargets(atLimit).length, MAX_TARGETS)
  assert.throws(() => normalizeTargets([...atLimit, { platform: 'x', mode: 'creator', uid: '999999' }]), error => error.code === 'targets_invalid')
  for (const duplicates of [
    [{ platform: 'x', mode: 'creator', uid: '1' }, { platform: 'x', mode: 'creator', uid: '1' }],
    // A display label never creates a distinct identity.
    [{ platform: 'x', mode: 'creator', uid: '1', label: 'A' }, { platform: 'x', mode: 'creator', uid: '1', label: 'B' }],
    [{ platform: 'x', mode: 'creator', handle: 'Somebody' }, { platform: 'x', mode: 'creator', handle: '@Somebody' }],
    [{ platform: 'weibo', mode: 'topic', topic: '旅行' }, { platform: 'weibo', mode: 'topic', topic: '旅行', topicKind: 'topic' }],
    [{ platform: 'x', mode: 'search', keyword: 'ai' }, { platform: 'x', mode: 'search', keyword: 'ai', sort: 'latest' }],
  ]) assert.throws(() => normalizeTargets(duplicates), error => error.code === 'targets_duplicate')
  // Sort and task mode are part of the identity, so these are different targets.
  assert.equal(normalizeTargets([{ platform: 'x', mode: 'search', keyword: 'ai' }, { platform: 'x', mode: 'search', keyword: 'ai', sort: 'top' }]).length, 2)
  assert.equal(normalizeTargets([{ platform: 'weibo', mode: 'topic', topic: '旅行' }, { platform: 'weibo', mode: 'topic', topic: '旅行', topicKind: 'super' }]).length, 2)
})

test('backend priority is explicit, then preference, then cdp, and auto is always rejected', () => {
  assert.equal(resolveBackend('cdp', 'computer_use'), 'cdp')
  assert.throws(() => resolveBackend('computer_use', 'cdp'), error => error.code === 'backend-retired-computer-use')
  assert.throws(() => resolveBackend(undefined, 'computer_use'), error => error.code === 'backend-retired-computer-use')
  assert.equal(resolveBackend(undefined, undefined), 'cdp')
  assert.equal(resolveBackend('CDP', undefined), 'cdp')
  assert.throws(() => resolveBackend('', 'computer_use'), error => error.code === 'backend-retired-computer-use')
  for (const [explicit, preference] of [['auto', undefined], [undefined, 'auto'], ['AUTO', 'cdp'], ['auto', 'computer_use']]) {
    assert.throws(() => resolveBackend(explicit, preference), error => error.code === 'backend_auto_unsupported' && error.message === 'backend_auto_unsupported')
  }
  for (const value of ['playwright', 'bsk', '9222', 'cdp, browserskill']) assert.throws(() => resolveBackend(value, undefined), error => error.code === 'backend_invalid')
  for (const value of [null, 9222, {}, []]) assert.throws(() => resolveBackend(value, undefined), error => error.code === 'backend_invalid')
})

test('count mode parsing accepts exactly fixed and best_effort with a validated fallback', () => {
  assert.equal(parseCountMode(undefined), 'fixed')
  assert.equal(parseCountMode(undefined, 'best_effort'), 'best_effort')
  assert.equal(parseCountMode('fixed'), 'fixed')
  assert.equal(parseCountMode('best_effort'), 'best_effort')
  assert.equal(parseCountMode('BEST_EFFORT'), 'best_effort')
  assert.equal(parseCountMode(' best_effort '), 'best_effort')
  assert.equal(parseCountMode(undefined, 'FIXED'), 'fixed')
  for (const value of ['', 'always', 'best effort', 'unlimited', null, 10, {}]) {
    assert.throws(() => parseCountMode(value), error => error.code === 'count_mode_invalid')
  }
  assert.throws(() => parseCountMode(undefined, 'sometimes'), error => error.code === 'count_mode_invalid')
})

test('an export selection is normalized, aliased and bounded', () => {
  const full = normalizeExportSelection({
    runId: 'run-2026.01_a-b', recordKinds: ['user_profiles', 'posts'], platforms: ['weibo', 'x', 'bilibili'],
    topics: ['旅行'], targets: ['weibo:topic:topic:旅行'], fields: ['tweet_id', 'author_id'], fieldGroups: ['engagement'],
    format: 'csv', fileName: 'runs-filtered.csv', overwrite: true,
  })
  assert.deepEqual(full, {
    runId: 'run-2026.01_a-b', recordKinds: ['user_profiles', 'posts'], platforms: ['bilibili', 'weibo', 'x'],
    topics: ['旅行'], targets: ['weibo:topic:topic:旅行'], fields: ['tweet_id', 'author_id'], fieldGroups: ['engagement'],
    format: 'csv', fileName: 'runs-filtered.csv', overwrite: true,
  })
  // The documented snake_case wire aliases resolve to the same selection.
  assert.deepEqual(normalizeExportSelection({ run_id: 'run-a', record_kinds: ['posts'], field_groups: ['engagement'], file_name: 'a.xlsx', platforms: ['x'] }),
    { runId: 'run-a', recordKinds: ['posts'], platforms: ['x'], topics: [], targets: [], fields: [], fieldGroups: ['engagement'], format: 'xlsx', fileName: 'a.xlsx', overwrite: false })
  const minimal = normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'] })
  assert.equal(minimal.format, 'xlsx')
  assert.equal(minimal.overwrite, false)
  assert.equal('fileName' in minimal, false)
  assert.deepEqual([minimal.platforms, minimal.topics, minimal.targets, minimal.fields, minimal.fieldGroups], [[], [], [], [], []])
  // Lists stay bounded and free of duplicates.
  assert.equal(normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], fields: Array.from({ length: 256 }, (unused, index) => `field_${index}`) }).fields.length, 256)
  assert.throws(() => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], fields: Array.from({ length: 257 }, (unused, index) => `field_${index}`) }), error => error.code === 'export_fields_invalid')
  for (const oversized of ['a'.repeat(201), 42, null]) {
    assert.throws(() => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], topics: [oversized] }), error => error.code === 'export_topics_invalid')
  }
  for (const runId of ['run-', 'RUN-a', 'run', 'run a', '', 42, null]) {
    assert.throws(() => normalizeExportSelection({ runId, recordKinds: ['posts'] }), error => error.code === 'run_id_invalid')
  }
  for (const recordKinds of [['comments'], ['posts', 'posts'], ['POSTS'], 'posts', [1]]) {
    assert.throws(() => normalizeExportSelection({ runId: 'run-a', recordKinds }), error => error.code === 'export_record_kinds_invalid')
  }
})

test('the export file name must be a plain base name', () => {
  for (const fileName of ['run.xlsx', 'run-2026.01_a-b.csv', '导出.xlsx']) {
    assert.equal(normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], fileName }).fileName, fileName)
  }
  for (const fileName of ['nested/run.xlsx', '..\\run.xlsx', 'run\u0000.xlsx', '', '.', '..', '/etc/passwd', 'a/b/c.xlsx', 'a'.repeat(256), 42, null]) {
    assert.throws(() => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], fileName }), error => error.code === 'export_file_name_invalid', String(fileName))
  }
  assert.throws(() => normalizeExportSelection({ runId: 'run-a', recordKinds: ['posts'], fileName: undefined, unknown: true }), error => error.code === 'export_arguments_invalid')
})
