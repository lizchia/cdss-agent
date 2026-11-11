#!/bin/bash
# Create the least-privilege login the API connects with (runs once, on an empty data volume).
# The password is passed as a psql variable and quoted with %L, so it is never spliced into SQL.
set -euo pipefail

: "${CDSS_DB_USER:?CDSS_DB_USER must be set}"
: "${CDSS_DB_PASSWORD:?CDSS_DB_PASSWORD must be set}"

psql -v ON_ERROR_STOP=1 \
     --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
     -v app_user="$CDSS_DB_USER" -v app_pw="$CDSS_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L IN ROLE cdss_readonly', :'app_user', :'app_pw')
\gexec
SELECT format('ALTER ROLE %I SET default_transaction_read_only = on', :'app_user')
\gexec
SQL
