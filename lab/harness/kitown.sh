# Ownership helpers (sourced). A container belongs to this kit only if it carries the compose
# project label "mastodon" AND its compose working_dir label equals this kit's workspace path.
KIT_NAMES="db redis pgbouncer web sidekiq streaming"
container_owner() { # name -> "ours" | "absent" | "foreign:<project>:<dir>"
  if ! docker container inspect "$1" >/dev/null 2>&1; then echo absent; return; fi
  _p="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project" }}' "$1" 2>/dev/null)"
  _d="$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$1" 2>/dev/null)"
  _ws="$(cd "$WORKSPACE" 2>/dev/null && pwd -P)"
  _dd="$(cd "$_d" 2>/dev/null && pwd -P)"
  if [ "$_p" = "mastodon" ] && [ -n "$_ws" ] && [ "$_dd" = "$_ws" ]; then echo ours; else echo "foreign:$_p:$_d"; fi
}
