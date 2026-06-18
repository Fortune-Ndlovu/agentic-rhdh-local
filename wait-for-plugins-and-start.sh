#!/bin/bash

set -euo pipefail

# This script is a workaround for podman-compose absence of support for depends_on

# Entrypoint for the main RHDH container.
# Waits for the dynamic plugin config to be generated,
# then starts the Backstage backend with appropriate config files.
#
# If user-supplied override files for catalog entities (users/components) exist,
# this script replaces their paths in the base config accordingly.

DYNAMIC_PLUGINS_CONFIG="dynamic-plugins-root/app-config.dynamic-plugins.yaml"
DEFAULT_APP_CONFIG="configs/app-config/app-config.yaml"
PATCHED_APP_CONFIG="generated/app-config.patched.yaml"

USER_APP_CONFIG="configs/app-config/app-config.local.yaml"
LIGHTSPEED_APP_CONFIG="developer-lightspeed/configs/app-config/app-config.lightspeed.local.yaml"
LEGACY_USER_APP_CONFIG="configs/app-config.local.yaml"

USERS_OVERRIDE="configs/catalog-entities/users.override.yaml"

mkdir -p generated
cp -f "$DEFAULT_APP_CONFIG" "$PATCHED_APP_CONFIG"

# Wait until the installer has fully completed (config written, temp dirs cleaned up)
INSTALL_COMPLETE="dynamic-plugins-root/.install-complete"
while [ ! -f "$INSTALL_COMPLETE" ]; do
  echo "Waiting for install-dynamic-plugins to finish ..."
  sleep 2
done

# Verify the dynamic plugin config was actually generated
if [ ! -f "$DYNAMIC_PLUGINS_CONFIG" ]; then
  echo "[error] $DYNAMIC_PLUGINS_CONFIG was not created — the installer may have failed. Check rhdh-plugins-installer logs."
  exit 1
fi

# Remove leftover temp directory so the PluginScanner doesn't try to load it as a plugin.
# This runs on every start (including restart), unlike the installer which only runs on fresh up.
if [ -d "dynamic-plugins-root/.catalog-index-temp" ]; then
  rm -rf "dynamic-plugins-root/.catalog-index-temp"
fi

# Apply overrides by replacing target paths in the patched config
if [ -f "$USERS_OVERRIDE" ]; then
  echo "Applying users override"
  sed -i "s|/opt/app-root/src/configs/catalog-entities/users.yaml|/opt/app-root/src/$USERS_OVERRIDE|" "$PATCHED_APP_CONFIG"
fi

# Add local config if available
EXTRA_CONFIGS=""
if [ -f "$USER_APP_CONFIG" ]; then
  echo "Using user config: $USER_APP_CONFIG"
  EXTRA_CONFIGS="$USER_APP_CONFIG"
elif [ -f "$LEGACY_USER_APP_CONFIG" ]; then
  echo "[warn] Using legacy app-config.local.yaml. This is deprecated. Please migrate to $USER_APP_CONFIG."
  EXTRA_CONFIGS="$LEGACY_USER_APP_CONFIG"
fi

if [ -f "$LIGHTSPEED_APP_CONFIG" ]; then
  echo "Using lightspeed config: $LIGHTSPEED_APP_CONFIG"
  EXTRA_CONFIGS="$EXTRA_CONFIGS $LIGHTSPEED_APP_CONFIG"
fi

EXTRA_CLI_ARGS=""
for config in $EXTRA_CONFIGS; do
  EXTRA_CLI_ARGS="$EXTRA_CLI_ARGS --config $config"
done

# Start Backstage backend
# Allows variable expansion for CLI args
# shellcheck disable=SC2086 
exec node packages/backend --no-node-snapshot \
  --config "app-config.yaml" \
  --config app-config.example.yaml \
  --config app-config.example.production.yaml \
  --config "$DYNAMIC_PLUGINS_CONFIG" \
  --config "$PATCHED_APP_CONFIG" $EXTRA_CLI_ARGS
