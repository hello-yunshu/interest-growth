# Interest Growth self-hosted server bundle

This archive is a clean-extract deployment bundle for the authenticated,
single-owner, online-first server profile. It contains the exact source and
Compose files used by the release build; it does not contain a database,
Source/Artifact data, credentials, signing keys or provider secrets.

```bash
tar -xzf interest-growth-server-<version>.tar.gz
cd interest-growth-server-<version>
cp .env.remote.example .env.remote
# Set PG_OWNER_BOOTSTRAP_TOKEN and any server-owned provider settings.
docker compose -f docker-compose.yml -f docker-compose.remote.yml \
  --env-file .env.remote up -d --build
```

The Compose services bind to loopback by default. Put an authenticated
Nginx/Caddy HTTPS edge in front of the ports before using another device.
SQLite, Sources and Artifacts live together in the persistent
`psychology_data` volume and must be backed up/restored as one unit using the
included application backup/restore functions.

`VERSION` and `SOURCE_SHA` identify the exact bundle source. Remote mode is not
offline sync and does not provide public multi-tenant signup.
