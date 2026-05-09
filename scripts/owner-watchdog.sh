#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_PATH="${1:-${ROOT_DIR}/scripts/owner-watchdog-config.example.json}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "ERR  config not found: $CONFIG_PATH"
  echo "Use scripts/owner-watchdog-config.example.json as template."
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "ERR  jq is required for owner-watchdog."
  exit 1
fi

if ! command -v cast >/dev/null 2>&1; then
  echo "ERR  cast is required for owner-watchdog."
  exit 1
fi

rpc_url="$(jq -r '.rpcUrl' "$CONFIG_PATH")"
state_file="$(jq -r '.stateFile' "$CONFIG_PATH")"
telegram_token="$(jq -r '.telegram.botToken // empty' "$CONFIG_PATH")"
telegram_chat_id="$(jq -r '.telegram.chatId // empty' "$CONFIG_PATH")"

if [[ -z "$rpc_url" || "$rpc_url" == "null" ]]; then
  echo "ERR  rpcUrl is required in config"
  exit 1
fi

mkdir -p "$(dirname "$state_file")"
touch "$state_file"

send_telegram() {
  local message="$1"
  if [[ -z "$telegram_token" || -z "$telegram_chat_id" ]]; then
    echo "WARN Telegram not configured; alert printed locally."
    echo "ALERT $message"
    return 0
  fi

  curl -sS -X POST "https://api.telegram.org/bot${telegram_token}/sendMessage" \
    -d "chat_id=${telegram_chat_id}" \
    --data-urlencode "text=${message}" >/dev/null
}

query_owner() {
  local contract="$1"
  cast call "$contract" "owner()(address)" --rpc-url "$rpc_url" 2>/dev/null || echo "0x0000000000000000000000000000000000000000"
}

jq -c '.contracts[]' "$CONFIG_PATH" | while read -r contract_json; do
  name="$(echo "$contract_json" | jq -r '.name')"
  address="$(echo "$contract_json" | jq -r '.address')"
  expected_owner="$(echo "$contract_json" | jq -r '.expectedOwner')"

  if [[ -z "$address" || "$address" == "null" || -z "$expected_owner" || "$expected_owner" == "null" ]]; then
    echo "WARN skip invalid contract config entry: $contract_json"
    continue
  fi

  current_owner="$(query_owner "$address")"
  key="${name}:${address}"
  previous_owner="$(jq -r --arg k "$key" '.[$k] // empty' "$state_file")"

  if [[ "$current_owner" != "$expected_owner" ]]; then
    send_telegram "Karma Owner Alert: ${name} at ${address} owner changed or unexpected. current=${current_owner}, expected=${expected_owner}"
  fi

  if [[ -n "$previous_owner" && "$previous_owner" != "$current_owner" ]]; then
    send_telegram "Karma Owner Change Detected: ${name} at ${address} previous=${previous_owner}, current=${current_owner}"
  fi

  tmp_file="${state_file}.tmp"
  jq --arg k "$key" --arg v "$current_owner" '.[$k] = $v' "$state_file" > "$tmp_file"
  mv "$tmp_file" "$state_file"
done

echo "OK owner-watchdog completed using ${CONFIG_PATH}"
