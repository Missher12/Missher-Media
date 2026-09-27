/** Read-only declarations; discovery never probes Chrome or reads a private profile. */
export function capabilities(version) {
  return {
    status: 'ok', version, coreProtocolVersion: 1, planSchemaVersion: 2, manifestSchemaVersion: 3,
    configuration: { inspected: false, reason: 'discovery-does-not-read-private-profile' },
    backends: {
      cdp: { status: 'unverified', supported: true, installed: 'unverified', configured: 'unverified', ready: false, reason: 'connection-and-platform-permissions-not-checked', independent: true },
    },
  }
}
