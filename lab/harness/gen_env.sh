#!/bin/bash
# Generate a fresh .env.production inside the workspace (new secrets every run).
# Usage: WORKSPACE=<dir> ./gen_env.sh   (defaults to $HOME/mastodon-ops)
set -e
. "$(cd "$(dirname "$0")" && pwd)/lib.sh"

[ -d "$WORKSPACE" ] || die "workspace $WORKSPACE does not exist (run setup_stack.sh first)"

log "Generating Mastodon secrets (one-off container; may take a minute)..."
# Ask the Mastodon image to mint the app secrets, then append the fixed deployment settings.
SECRETS="$(docker run --rm tootsuite/mastodon:v4.7.2 bash -lc '
  echo SECRET_KEY_BASE=$(bundle exec rails secret 2>/dev/null)
  echo OTP_SECRET=$(bundle exec rails secret 2>/dev/null)
  bundle exec rails mastodon:webpush:generate_vapid_key 2>/dev/null
  bundle exec rails db:encryption:init 2>/dev/null
' | grep -E '^[A-Z_]+=')"

{
  printf '%s\n' "$SECRETS"
  cat <<EOT
LOCAL_DOMAIN=mastodon.test
RAILS_ENV=production
NODE_ENV=production
REDIS_HOST=redis
REDIS_PORT=6379
DB_HOST=pgbouncer
DB_USER=mastodon
DB_NAME=mastodon_production
DB_PASS=$OLD_PW
DB_PORT=6432
PREPARED_STATEMENTS=false
ES_ENABLED=false
SMTP_DELIVERY_METHOD=test
STREAMING_API_BASE_URL=wss://streaming.mastodon.test
RAILS_LOG_LEVEL=warn
EOT
} > "$WORKSPACE/.env.production"

# Sanity: confirm the app secrets landed (image output format can drift between versions).
for k in SECRET_KEY_BASE OTP_SECRET VAPID_PRIVATE_KEY VAPID_PUBLIC_KEY \
         ACTIVE_RECORD_ENCRYPTION_PRIMARY_KEY ACTIVE_RECORD_ENCRYPTION_DETERMINISTIC_KEY \
         ACTIVE_RECORD_ENCRYPTION_KEY_DERIVATION_SALT; do
  grep -q "^$k=" "$WORKSPACE/.env.production" || die "secret $k missing from generated .env.production"
done
log "wrote $WORKSPACE/.env.production"
