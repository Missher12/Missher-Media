import { defineConfig } from 'tsdown'

export default defineConfig({
  entry: { index: 'src/index.ts' },
  outDir: 'lib',
  format: ['esm'],
  platform: 'node',
  target: 'node22.19',
  fixedExtension: false,
  dts: true,
  clean: true,
  banner: '/* Copyright (c) 2026 Missher. All rights reserved. See LICENSE. Third-party licenses remain in effect. */',
})
