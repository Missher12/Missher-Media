import { describe, expect, it, vi } from 'vitest'
import { apply } from '../src/index.js'

describe('installed Agent workflow', () => {
  it('contributes bounded guidance through the native host service', () => {
    const section = vi.fn()
    const register = vi.fn((_tool: { name: string; description: string }) => () => {})
    const get = vi.fn((name: string) => name === 'systemPrompt' ? { section } : undefined)
    apply({ get, tools: { register }, dshHomePath: () => '/tmp/agent-guidance-dsh' } as never)
    expect(section).toHaveBeenCalledOnce()
    expect(section.mock.calls[0][0]).toMatchObject({ name: 'media-missher:agent-guidance', order: 146 })
    const text = section.mock.calls[0][0].text
    for (const value of ['media_missher_setup', 'media_missher_collect', 'media_missher_runs', '600', '10', 'manual login']) expect(text).toContain(value)
    expect(register.mock.calls.map(([tool]) => tool.name)).toEqual(['media_missher_collect', 'media_missher_runs', 'media_missher_setup'])
    expect(text).toContain('backend-retired-computer-use')
    expect(text).not.toContain('cdp or browserskill')
  })

  it('keeps discoverable tools available when the optional prompt service is absent', () => {
    const register = vi.fn((_tool: { name: string; description: string }) => () => {})
    apply({ get: () => undefined, tools: { register }, dshHomePath: () => '/tmp/agent-guidance-dsh' } as never)
    expect(register).toHaveBeenCalledTimes(3)
    for (const [tool] of register.mock.calls) expect(tool.description.length).toBeGreaterThan(100)
  })
})
