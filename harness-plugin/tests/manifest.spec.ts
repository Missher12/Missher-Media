import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const root = resolve(import.meta.dirname, '..')

describe('Harness Bundle manifest', () => {
  it('declares the private macOS bundle and 4x10 defaults', async () => {
    const manifest = JSON.parse(await readFile(resolve(root, 'package.json'), 'utf8'))
    const patch = await readFile(resolve(root, 'cordis.patch.yml'), 'utf8')
    const buildConfig = await readFile(resolve(root, 'tsdown.config.ts'), 'utf8')

    expect(manifest).toMatchObject({
      name: 'dsh-media-missher',
      version: '0.1.1',
      type: 'module',
      license: 'UNLICENSED',
      private: true,
      os: ['darwin'],
      dsh: { bundle: { patch: './cordis.patch.yml' } },
    })
    expect(manifest.dependencies['@deepseek-ai/dsh-tools']).toBeUndefined()
    expect(manifest.devDependencies['@deepseek-ai/dsh-tools']).toBe('0.1.1-rc.2')
    expect(patch).toContain('id: media-missher')
    expect(patch).toContain('name: dsh-media-missher')
    expect(patch).toContain('defaultPlatforms: bilibili,xhs,douyin,weibo')
    expect(patch).toContain('defaultCount: 10')
    expect(patch.match(/- insert:/gu)).toHaveLength(1)
    expect(buildConfig).toContain("outDir: 'lib'")
    expect(buildConfig).toContain("entry: { index: 'src/index.ts' }")
  })
})
