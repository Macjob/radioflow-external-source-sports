# Hosted Sports add-on service

This service is a separate long-running container on the existing VPS. It does not run inside RadioFlow and does not replace the self-hosted publisher.

## Required secrets

- `API_FOOOTBAL`: API-Football v3 key, sent only as `x-apisports-key` by the backend.
- `SPORTS_CONFIG_SIGNING_SECRET`: at least 32 random bytes. It derives opaque `configId` values during the one-time exchange; rotate only with an explicit migration because existing IDs depend on it.
- `SPORTS_ALLOWED_CALLBACK_ORIGINS`: comma-separated RadioFlow deployment origins. Production must not retain localhost defaults.

The SQLite database stores only `SHA-256(configId)`. That is sufficient to authenticate `/addon/events`, locate an existing configuration for reconfiguration, disable the old configuration after rotation, and deduplicate ownership-free configuration records. The raw `configId` exists only in RadioFlow's encrypted store and in the `X-RadioFlow-Config-Id` request header.

The API-Football subscription must grant access to the current season for the configured competitions. A valid Free key was verified against the official API, but on 2026-08-12 that plan reported access only to seasons 2022-2024. It returned Primera División 2024 with 16 teams, but it cannot validate or operate the current 2026 fixture vertical. Treat an upgrade/current-season entitlement and a successful `/teams` plus `/fixtures` smoke test as deployment gates.

## Build and run

```bash
cd /opt/radioflow-sports/source
GIT_SHA="$(git rev-parse --short=12 HEAD)"
docker build --pull --file Dockerfile.service --tag "radioflow-sports-addon:${GIT_SHA}" .
cp deploy/hosted.env.example /opt/radioflow-sports/hosted.env
chmod 600 /opt/radioflow-sports/hosted.env
RADIOFLOW_SPORTS_IMAGE_TAG="$GIT_SHA" SPORTS_HOSTED_ENV_FILE=/opt/radioflow-sports/hosted.env \
  docker compose --file deploy/docker-compose.hosted.yml up -d
```

The compose file publishes only `127.0.0.1:8010`. Install the Nginx example after adapting certificate paths, then verify:

```bash
curl --fail https://addons.radioflow.media/sports/manifest.json
curl --fail https://addons.radioflow.media/sports/health
```

The public RadioFlow deployment must set:

```env
RADIOFLOW_SPORTS_ADDON_MANIFEST_URL=https://addons.radioflow.media/sports/manifest.json
```

Do not deploy from a PR merely because CI is green. Merge, VPS rollout, and end-to-end verification remain separate approvals.
