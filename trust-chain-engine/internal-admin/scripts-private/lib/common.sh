#!/usr/bin/env bash

# Shared shell helpers for TrustChain scripts.

tc_root_dir() {
  local src="${BASH_SOURCE[0]}"
  while [[ -L "$src" ]]; do
    src="$(readlink "$src")"
  done
  local dir
  dir="$(cd "$(dirname "$src")/../.." && pwd)"
  echo "$dir"
}

tc_die() {
  echo "Error: $*" >&2
  exit 1
}

tc_require_arg() {
  local flag="$1"
  local remaining="$2"
  if [[ "$remaining" -lt 2 ]]; then
    tc_die "${flag} requires a value"
  fi
}

tc_abs_path() {
  local root="$1"
  local path="$2"
  if [[ "$path" == /* ]]; then
    echo "$path"
  else
    echo "${root}/${path}"
  fi
}

usage_if_requested() {
  if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    usage
    exit 0
  fi
}
