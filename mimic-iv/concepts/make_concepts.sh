#!/bin/bash
# This script generates the concepts in the BigQuery table mimiciv_derived.
export TARGET_DATASET=mimiciv_derived
export METADATA_TABLE="_metadata"
export MIMIC_VERSION="3.1"

# specify bigquery query command options
# note: max_rows=1 *displays* only one row, but all rows are inserted into the destination table
BQ_OPTIONS=(--quiet --headless --max_rows=0 --use_legacy_sql=False --replace)

# drop the existing tables in the target dataset
for TABLE in $(bq ls "physionet-data:${TARGET_DATASET}" | cut -d' ' -f3);
do
    # skip the first line of dashes
    if [[ "${TABLE:0:2}" == '--' ]]; then
      continue
    fi
  echo "Dropping table ${TARGET_DATASET}.${TABLE}"
  bq rm -f -q "${TARGET_DATASET}.${TABLE}"
done

# create a _version table to store the mimic-iv version, git commit hash, and latest git tag
GIT_COMMIT_HASH=$(git rev-parse HEAD)
LATEST_GIT_TAG=$(git describe --tags --abbrev=0)

echo "Creating ${TARGET_DATASET}.${METADATA_TABLE} table"
bq query <<EOF
CREATE TABLE IF NOT EXISTS \`physionet-data.${TARGET_DATASET}.${METADATA_TABLE}\` (
  attribute STRING,
  value STRING
);

TRUNCATE TABLE \`physionet-data.${TARGET_DATASET}.${METADATA_TABLE}\`;

INSERT INTO \`physionet-data.${TARGET_DATASET}.${METADATA_TABLE}\` (attribute, value)
VALUES
  ('mimic_version', '${MIMIC_VERSION}'),
  ('mimic_code_version', '${LATEST_GIT_TAG}'),
  ('mimic_code_commit_hash', '${GIT_COMMIT_HASH}');
EOF

# generate the tables in dependency order: each concept comes after the
# concepts it reads. The order is worked out from the SQL by mimic_utils,
# installed with `pip install -e .` from the repository root.
if ! CONCEPT_ORDER=$(mimic_utils concept_order .); then
    echo "Could not work out the concept build order. Is mimic_utils installed?" >&2
    exit 1
fi

while IFS= read -r fn_path; do
    # table name is file name minus extension
    tbl=$(basename "${fn_path}" .sql)
    echo "Generating ${TARGET_DATASET}.${tbl}"
    bq query "${BQ_OPTIONS[@]}" --destination_table="${TARGET_DATASET}.${tbl}" < "${fn_path}"
done <<< "${CONCEPT_ORDER}"
