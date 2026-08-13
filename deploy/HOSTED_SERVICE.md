# Hosted Sports add-on service

This service is a separate long-running container on the existing VPS. It does not run inside RadioFlow and does not replace the self-hosted publisher.

## Provider configuration and required secrets

- `SPORTS_PROVIDER=thesportsdb`: selects the single deterministic Alpha provider.
- `THESPORTSDB_API_KEY`: `123` is TheSportsDB's documented Free v1 key; replace it with the hosted operator's key when appropriate.
- `SPORTS_COMPETITIONS_FILE`: technical catalog containing internal competition IDs and provider mappings.
- `SPORTS_SCHEDULE_TIMEZONE`: final display timezone used when translating UTC matches to `suggest_block` schedule fields.
- `SPORTS_CONFIG_SIGNING_SECRET`: at least 32 random bytes. It derives opaque `configId` values during the one-time exchange; rotate only with an explicit migration because existing IDs depend on it.
- `SPORTS_ALLOWED_CALLBACK_ORIGINS`: comma-separated RadioFlow deployment origins. Production must not retain localhost defaults.

The SQLite database stores only `SHA-256(configId)`. That is sufficient to authenticate `/addon/events`, locate an existing configuration for reconfiguration, disable the old configuration after rotation, and deduplicate ownership-free configuration records. The raw `configId` exists only in RadioFlow's encrypted store and in the `X-RadioFlow-Config-Id` request header.

TheSportsDB is the Alpha reference provider, not an Addon Protocol dependency. Its Free v1 limits include 30 requests/minute, 1 event from `eventsnextleague.php`, 15 from `eventsseason.php`, and 10 teams from `search_all_teams.php`. Live Chile 2026 evidence showed that the season response contains old fixtures while the next-league response contains the upcoming match. The service combines both schedules and builds the wizard team list from both the team endpoint and season participants. All equivalent calls share the same cache. Treat a successful 16-team and upcoming-match smoke test as a deployment gate because Free responses can still be incomplete.

The provider normalizes `dateEvent` + `strTime` to UTC and rejects ambiguous or contradictory timestamps. The wizard receives only internal competition/team IDs. Provider IDs and credentials never leave this service.

The web-configurable service has not yet been deployed, so there is no production data migration. Existing development SQLite files created by the API-Football branch contain numeric provider IDs and must be discarded or reconfigured; do not promote them to the hosted volume.

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
