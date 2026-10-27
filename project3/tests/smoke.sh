#!/usr/bin/env bash
set -euo pipefail

program="${1:-build/chess_search}"
fens=(
  'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1'
  'r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1'
  '7k/8/5KQ1/8/8/8/8/8 w - - 0 1'
  '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1'
  '7k/6Q1/6K1/8/8/8/8/8 b - - 0 1'
  '4k3/P7/8/8/8/8/8/4K3 w - - 0 1'
  '4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1'
)

score_of() {
  local line="$1"
  [[ "$line" =~ (^|[[:space:]])score=([-0-9]+) ]] || return 1
  printf '%s' "${BASH_REMATCH[2]}"
}

count=0
for fen in "${fens[@]}"; do
  for depth in 1 2 3; do
    serial="$($program --backend serial --depth "$depth" --fen "$fen")"
    expected="$(score_of "$serial")"
    minimax="$($program --backend minimax --depth "$depth" --fen "$fen")"
    [[ "$(score_of "$minimax")" == "$expected" ]]
    omp="$($program --backend omp --threads 4 --depth "$depth" --fen "$fen")"
    omp_pv="$($program --backend omp-pv --threads 4 --depth "$depth" --fen "$fen")"
    if (( depth >= 2 )); then
      frontier="$($program --backend omp --threads 4 --split-depth 2 --depth "$depth" --fen "$fen")"
      [[ "$(score_of "$frontier")" == "$expected" ]]
    fi
    if (( depth >= 3 )); then
      frontier3="$($program --backend omp --threads 4 --split-depth 3 --depth "$depth" --fen "$fen")"
      [[ "$(score_of "$frontier3")" == "$expected" ]]
    fi
    gpu_host="$($program --backend gpu-host --depth "$depth" --fen "$fen")"
    [[ "$(score_of "$omp")" == "$expected" ]]
    [[ "$(score_of "$omp_pv")" == "$expected" ]]
    [[ "$(score_of "$gpu_host")" == "$expected" ]]
    [[ "$gpu_host" == *'ran_on_device=0'* ]]
    count=$((count + 1))
  done
done

if "$program" --backend gpu --depth 2 >/dev/null 2>&1; then
  echo 'GPU backend unexpectedly accepted CPU fallback' >&2
  exit 1
fi

echo "Passed: $count position/depth comparisons across minimax, serial alpha-beta, OpenMP, seeded-root OpenMP and target host fallback."
