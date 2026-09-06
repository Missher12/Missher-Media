import { describe, expect, it } from 'vitest'
import {
  normalizeCollectArgs,
  normalizePluginConfig,
} from '../src/config.js'

const dshHome = '/Users/test/.dsh'
const userHome = '/Users/test'

describe('Media plugin configuration', () => {
  it('resolves the zero-argument request to four platforms times ten', () => {
    const config = normalizePluginConfig({}, dshHome, userHome)

    expect(normalizeCollectArgs({}, config)).toEqual({
      platforms: ['bilibili', 'xhs', 'douyin', 'weibo'],
      platformText: 'bilibili,xhs,douyin,weibo',
      count: 10,
      xhsComments: 0,
      allowNavigation: true,
    })
    expect(config).toMatchObject({
      profilePath: '/Users/test/.config/media-missher/profile.json',
      runtimeHome: '/Users/test/.local/share/media-missher',
      outputRoot: '/Users/test/.dsh/media-missher/runs',
      platformTimeoutSeconds: 300,
      executionTimeoutSeconds: 1260,
      maxCount: 50,
    })
  })

  it.each([
    ['bilibili,bilibili', 'platforms_duplicate'],
    ['bilibili,unknown', 'platforms_invalid'],
    ['', 'platforms_empty'],
    ['bilibili,', 'platforms_invalid'],
    [',weibo', 'platforms_invalid'],
  ])('rejects invalid platform selection %s', (platforms, code) => {
    const config = normalizePluginConfig({}, dshHome, userHome)
    expect(() => normalizeCollectArgs({ platforms }, config)).toThrow(code)
  })

  it.each([0, 51, 1.5, Number.NaN])('rejects invalid count %s', (count) => {
    const config = normalizePluginConfig({}, dshHome, userHome)
    expect(() => normalizeCollectArgs({ count }, config)).toThrow('count_invalid')
  })

  it.each([-1, 101, 1.5, Number.NaN])('rejects invalid XHS comment count %s', (xhsComments) => {
    const config = normalizePluginConfig({}, dshHome, userHome)
    expect(() => normalizeCollectArgs({ xhs_comments: xhsComments }, config)).toThrow('xhs_comments_invalid')
  })

  it('keeps canonical platform order for a subset', () => {
    const config = normalizePluginConfig({}, dshHome, userHome)
    expect(normalizeCollectArgs({ platforms: 'weibo,bilibili', count: 3 }, config)).toMatchObject({
      platforms: ['bilibili', 'weibo'],
      platformText: 'bilibili,weibo',
      count: 3,
    })
  })

  it.each([
    [{ profilePath: 'relative.json' }, 'profile_path_invalid'],
    [{ runtimeHome: '/' }, 'runtime_home_invalid'],
    [{ outputRoot: '/Users/test/.dsh' }, 'output_root_invalid'],
    [{ platformTimeoutSeconds: 0 }, 'platform_timeout_invalid'],
    [{ executionTimeoutSeconds: Number.POSITIVE_INFINITY }, 'execution_timeout_invalid'],
    [{ maxCount: 0 }, 'max_count_invalid'],
  ])('rejects unsafe plugin config %#', (input, code) => {
    expect(() => normalizePluginConfig(input, dshHome, userHome)).toThrow(code)
  })
  it('rejects wrong platform types with a fixed diagnostic', () => {
    const config = normalizePluginConfig({}, dshHome, userHome)
    expect(() => normalizeCollectArgs({ platforms: 42 as never }, config)).toThrow('platforms_invalid')
  })

  it('rejects comments requested without Xiaohongshu', () => {
    const config = normalizePluginConfig({}, dshHome, userHome)
    expect(() => normalizeCollectArgs({ platforms: 'weibo', xhs_comments: 1 }, config))
      .toThrow('xhs_comments_platform_invalid')
  })

  it.each([null, [], { count: null }, { cookie: 'synthetic' }])('rejects malformed or undeclared arguments %#', (input) => {
    const config = normalizePluginConfig({}, dshHome, userHome)
    expect(() => normalizeCollectArgs(input, config)).toThrow('arguments_invalid')
  })

})
