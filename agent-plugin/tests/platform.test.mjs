import assert from 'node:assert/strict'
import { test } from 'node:test'
import { assertWslStorage, checkStorage, wslEnvironment } from '../src/platform.mjs'

const rootMount = '1 0 8:1 / / rw - ext4 /dev/sda rw\n'
test('WSL private paths require a native Linux HOME including the effective mount beneath it', () => {
  assert.doesNotThrow(() => assertWslStorage('/home/user', ['/home/user/.local/share/media', '/home/user/.config/media/profile.json'], rootMount))
  assert.throws(() => assertWslStorage('/mnt/c/Users/user', ['/mnt/c/Users/user/profile'], rootMount), /platform_wsl_home_required/)
  assert.throws(() => assertWslStorage('/home/user', ['/home/user-other/out'], rootMount), /platform_wsl_home_required/)
  const mounted = rootMount + '2 1 0:10 / /home/user/windows rw - 9p C:\\134 rw\n'
  assert.throws(() => assertWslStorage('/home/user', ['/home/user/windows/result'], mounted), /platform_wsl_native_storage_required/)
  const nested = rootMount + '2 1 0:10 / /home/user/config/browser/chrome-profile rw - 9p C: rw\n'
  assert.throws(() => assertWslStorage('/home/user', ['/home/user/config/browser'], nested), /platform_wsl_native_storage_required/)
  assert.doesNotThrow(() => assertWslStorage('/home/user', ['/home/user/unrelated-native-files'], nested))
  const spaced = rootMount + '2 1 0:10 / /home/user/drive\\040alias rw - drvfs D: rw\n'
  assert.throws(() => assertWslStorage('/home/user', ['/home/user/drive alias/result'], spaced), /platform_wsl_native_storage_required/)
  assert.throws(() => assertWslStorage('/home/user', ['/home/user/result'], 'malformed'), /platform_wsl_storage_unverified/)
})
test('Linux root stops before any native environment read; ordinary macOS stays independent of WSL', async () => {
  await assert.rejects(checkStorage('/root', [], { platform: 'linux', uid: 0 }), /platform_linux_user_required/)
  await checkStorage('/Users/user', ['/private/local'], { platform: 'darwin', uid: 501, distribution: 'Ubuntu' })
  assert.equal(wslEnvironment({ platform: 'linux', kernel: '6.6.87-microsoft-standard-WSL2', distribution: '' }), true)
  assert.equal(wslEnvironment({ platform: 'linux', kernel: 'ordinary-linux', distribution: undefined }), false)
  await checkStorage('/home/user', ['/home/user/result'], { platform: 'linux', uid: 1000, distribution: 'Ubuntu', mountinfo: rootMount })
})
