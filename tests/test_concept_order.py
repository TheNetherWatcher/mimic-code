"""Tests for working out the build order of derived concepts."""
import re
from pathlib import Path

import pytest

from mimic_utils.concept_order import concept_dependencies, concept_order

REPO_ROOT = Path(__file__).resolve().parent.parent
CONCEPTS_DIR = REPO_ROOT / "mimic-iv" / "concepts"


def write_concepts(folder: Path, concepts: dict):
    for relative, sql in concepts.items():
        path = folder / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sql)


def test_dependencies_come_from_derived_tables(tmp_path):
    write_concepts(tmp_path, {
        "demographics/age.sql": "SELECT * FROM `physionet-data.mimiciv_hosp.patients`",
        "score/oasis.sql": (
            "WITH age AS (SELECT 1 AS x) "
            "SELECT * FROM `physionet-data.mimiciv_derived.age` a "
            "INNER JOIN `physionet-data.mimiciv_icu.icustays` ie USING (subject_id)"
        ),
    })
    assert concept_dependencies(tmp_path) == {
        "demographics/age.sql": set(),
        "score/oasis.sql": {"demographics/age.sql"},
    }


def test_order_puts_concepts_after_what_they_read(tmp_path):
    write_concepts(tmp_path, {
        "a/first.sql": "SELECT 1 AS x",
        "b/second.sql": "SELECT * FROM `physionet-data.mimiciv_derived.first`",
        "a/third.sql": "SELECT * FROM `physionet-data.mimiciv_derived.second`",
        "b/other.sql": "SELECT 2 AS x",
    })
    assert concept_order(tmp_path) == [
        ["a/first.sql", "b/other.sql"],
        ["b/second.sql"],
        ["a/third.sql"],
    ]


def test_unknown_derived_table_is_an_error(tmp_path):
    write_concepts(tmp_path, {
        "a.sql": "SELECT * FROM `physionet-data.mimiciv_derived.missing`",
    })
    with pytest.raises(ValueError, match="missing"):
        concept_dependencies(tmp_path)


def test_cycle_is_an_error(tmp_path):
    write_concepts(tmp_path, {
        "a.sql": "SELECT * FROM `physionet-data.mimiciv_derived.b`",
        "b.sql": "SELECT * FROM `physionet-data.mimiciv_derived.a`",
    })
    with pytest.raises(ValueError, match="cycle"):
        concept_order(tmp_path)


def test_duplicate_table_name_is_an_error(tmp_path):
    write_concepts(tmp_path, {"a/x.sql": "SELECT 1", "b/x.sql": "SELECT 2"})
    with pytest.raises(ValueError, match="x"):
        concept_dependencies(tmp_path)


def test_mimic_iv_concepts_have_an_order():
    stages = concept_order(CONCEPTS_DIR)
    built = [path for stage in stages for path in stage]
    assert sorted(built) == sorted(
        p.relative_to(CONCEPTS_DIR).as_posix() for p in CONCEPTS_DIR.rglob("*.sql")
    )


# The DuckDB and PostgreSQL build scripts list the concepts by hand, so check
# they build every concept, each after the concepts it reads.
@pytest.mark.parametrize("script, pattern", [
    ("concepts_duckdb/duckdb.sql", r"^\.read\s+(\S+\.sql)"),
    ("concepts_postgres/postgres-make-concepts.sql", r"^\\i\s+(\S+\.sql)"),
])
def test_build_script_follows_dependencies(script, pattern):
    text = (REPO_ROOT / "mimic-iv" / script).read_text()
    listed = re.findall(pattern, text, flags=re.MULTILINE)
    dependencies = concept_dependencies(CONCEPTS_DIR)

    concepts = [path for path in listed if path in dependencies]
    assert sorted(set(concepts)) == sorted(dependencies), "concepts missing from the script"

    built = set()
    for path in concepts:
        assert dependencies[path] <= built, f"{path} is built before {dependencies[path] - built}"
        built.add(path)
