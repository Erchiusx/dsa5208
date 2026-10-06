#!/usr/bin/env bash
# Download official data.gov.sg annual rainfall CSVs for DSA5208 Project 2.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_dir="$(cd "${script_dir}/.." && pwd)"
raw_dir="${project_dir}/data/raw"
metadata_dir="${project_dir}/data/metadata"
manifest="${metadata_dir}/download-manifest.json"
api_base="https://api-open.data.gov.sg/v1/public/api/datasets"

mkdir -p "${raw_dir}" "${metadata_dir}"

declare -A dataset_ids=(
  [2017]=d_1990a5a1aeaf3dd243cf4dae294a61c4
  [2018]=d_024fb501ce7092b71bb713eaf54fa7eb
  [2019]=d_61995f092320e7155b7528050880b502
  [2020]=d_9e7de44094f876f6804b8b5bcee45c81
  [2021]=d_3b41598f74f1f11fc3430348fea51af5
  [2022]=d_42d64cc6c176ace1c52fbb40b9ede302
  [2023]=d_f864cc30d58b467db83659ad17c737bf
  [2024]=d_a0b69d3e02576a1fd0ab673e71f83507
)
declare -A expected_bytes=(
  [2017]=1007353435 [2018]=879809824 [2019]=963396474 [2020]=1200974276
  [2021]=1327644674 [2022]=1343853171 [2023]=1269318635 [2024]=1219623324
)

if ! command -v curl >/dev/null || ! command -v jq >/dev/null; then
  echo "This script requires curl and jq." >&2
  exit 1
fi

years=("$@")
if [[ ${#years[@]} -eq 0 ]]; then
  years=({2017..2024})
fi

for year in "${years[@]}"; do
  if [[ ! ${dataset_ids[$year]+_} ]]; then
    echo "Unknown year: ${year}; choose an integer from 2017 through 2024." >&2
    exit 2
  fi
  dataset_id="${dataset_ids[$year]}"
  output="${raw_dir}/rainfall_${year}.csv"
  partial="${raw_dir}/rainfall_${year}.csv.partial"

  # A CSV is created only after a full transfer has completed and is atomically
  # renamed. data.gov.sg's metadata datasetSize is not the size of its exported
  # CSV object, so it cannot safely be used as a completion check.
  if [[ -f "${output}" ]]; then
    echo "Keeping existing ${output}"
    continue
  fi

  echo "Requesting a download URL for ${year} (${dataset_id})..."
  # The API response contains a short-lived, AWS-signed download URL.  Extract
  # it directly in the pipeline: persisting that response would leak temporary
  # credentials into a working tree or commit.
  url="$(curl --fail --silent --show-error --retry 4 --retry-all-errors \
    "${api_base}/${dataset_id}/poll-download" | jq -er '.data.url | select(type == "string" and length > 0)')"

  # A one-byte range probe reveals the exact exported-object size. This lets a
  # previously interrupted transfer be finalized without trusting datasetSize.
  headers="$(curl --fail --silent --show-error --location --range 0-0 \
    --dump-header - --output /dev/null "${url}")"
  remote_bytes="$(printf '%s\n' "${headers}" | tr -d '\r' | grep -i '^content-range:' | sed 's|.*/||')"
  if [[ ! "${remote_bytes}" =~ ^[0-9]+$ ]]; then
    echo "Could not obtain the exported-object size for ${year}." >&2
    exit 1
  fi
  if [[ -f "${partial}" && "$(stat -c '%s' "${partial}")" -eq "${remote_bytes}" ]]; then
    mv "${partial}" "${output}"
    echo "Finalized previously completed ${output}"
    continue
  fi
  if [[ -f "${partial}" && "$(stat -c '%s' "${partial}")" -gt "${remote_bytes}" ]]; then
    quarantined="${partial}.oversized-$(date -u +%Y%m%dT%H%M%SZ)"
    mv "${partial}" "${quarantined}"
    echo "Quarantined oversized partial as ${quarantined}" >&2
  fi

  echo "Downloading ${year} (resumable)..."
  curl --fail --location --continue-at - --retry 4 --retry-all-errors --no-progress-meter \
    --output "${partial}" "${url}"
  if [[ "$(stat -c '%s' "${partial}")" -ne "${remote_bytes}" ]]; then
    echo "Incomplete ${year}: downloaded size differs from source object." >&2
    exit 1
  fi
  mv "${partial}" "${output}"
done

python3 "${script_dir}/verify_raw_data.py" --write-manifest "${manifest}"
