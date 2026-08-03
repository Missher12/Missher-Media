# Configuration

Configuration precedence is CLI, environment, then private profile.

## Environment

- `MEDIA_MISSHER_ENGINE_ROOT`: external skill root containing `scripts/` and `engine/.venv/bin/python`.
- `MEDIA_MISSHER_DATA_ROOT`: parent directory for unique private run directories.
- `MEDIA_MISSHER_CDP_URL`: existing Chrome CDP base URL; default is local port `9222`.
- `MEDIA_MISSHER_PROFILE_CONFIG`: path to a private JSON profile.

Do not store secrets, IDs, browser state, or personal paths in the installable skill.

## Private profile

Place the profile outside the skill and repository. Set exact mode `0600`.

```bash
chmod 600 /secure/path/media-missher-profile.json
```

Example structure using invented values:

```json
{
  "engine_root": "/secure/path/external-media-runtime",
  "data_root": "/secure/path/media-runs",
  "cdp_url": "http://127.0.0.1:9222",
  "platform_uids": {
    "bilibili": "configured-bilibili-id",
    "xhs": "configured-xhs-id",
    "douyin": "configured-douyin-id",
    "weibo": "configured-weibo-id"
  }
}
```

The adapter rejects a profile inside the repository or installed skill, a profile not using exact mode `0600`, an unknown platform, an empty target, a negative count, a fractional count, and a negative or non-finite timeout.

The profile must not contain Feishu credentials. This skill does not read such credentials.
