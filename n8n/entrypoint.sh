#!/bin/sh
set -e
if [ -n "$N8N_DB_URL" ]; then
  eval "$(node -e '
    const u = new URL(process.env.N8N_DB_URL);
    const q = s => "\x27" + String(s).replace(/\x27/g, "\x27\\\x27\x27") + "\x27";
    console.log("export DB_POSTGRESDB_HOST=" + q(u.hostname));
    console.log("export DB_POSTGRESDB_PORT=" + q(u.port || 5432));
    console.log("export DB_POSTGRESDB_USER=" + q(decodeURIComponent(u.username)));
    console.log("export DB_POSTGRESDB_PASSWORD=" + q(decodeURIComponent(u.password)));
    console.log("export DB_POSTGRESDB_DATABASE=" + q(u.pathname.slice(1)));
  ')"
fi
if [ -n "$PROJECT_CA_CERT" ]; then
  export DB_POSTGRESDB_SSL_CA="$(echo "$PROJECT_CA_CERT" | base64 -d)"
  export DB_POSTGRESDB_SSL_REJECT_UNAUTHORIZED=true
fi
exec /docker-entrypoint.sh "$@"
