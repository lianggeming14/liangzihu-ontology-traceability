#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1 <<'SQL'
\getenv api_password LZO_LOCAL_API_PASSWORD
\getenv worker_password LZO_LOCAL_WORKER_PASSWORD
CREATE ROLE lzo_local_api LOGIN PASSWORD :'api_password';
CREATE ROLE lzo_local_worker LOGIN PASSWORD :'worker_password';
SQL
