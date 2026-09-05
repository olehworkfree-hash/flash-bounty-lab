#!/usr/bin/env bash
set -euo pipefail
# Linux/macOS/WSL. Uses the official installer, then pins the reviewed release.
# Review the installer before executing it; no --force / attestation bypass.
command -v curl >/dev/null
installer="$(mktemp)"
trap 'rm -f "$installer"' EXIT
curl --fail --location --proto '=https' --tlsv1.2 https://getfoundry.sh/install -o "$installer"
bash "$installer"
export PATH="$HOME/.foundry/bin:$PATH"
foundryup --install v1.8.1
forge --version
anvil --version
# forge build will download/use the Solidity compiler pinned in foundry.toml.
forge build
