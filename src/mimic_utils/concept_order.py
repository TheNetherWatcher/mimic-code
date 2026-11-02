"""Work out the order in which derived concepts must be built.

Each concept is a SQL file whose table is named after the file. A concept
depends on another when its query reads that concept's table from the derived
schema, so the build order follows from the SQL itself rather than from
hand-kept lists.
"""
import os
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Dict, List, Set, Union

import sqlglot
from sqlglot import exp


def _concept_files(concepts_dir: Path) -> Dict[str, str]:
    """Map each concept's table name to its path relative to ``concepts_dir``."""
    files = {}
    for path in sorted(concepts_dir.rglob("*.sql")):
        relative = path.relative_to(concepts_dir).as_posix()
        if path.stem in files:
            raise ValueError(
                f"Two concepts create the table {path.stem}: "
                f"{files[path.stem]} and {relative}"
            )
        files[path.stem] = relative
    return files


def concept_dependencies(
        concepts_dir: Union[str, os.PathLike],
        derived_schema: str = "mimiciv_derived",
    ) -> Dict[str, Set[str]]:
    """Return the concepts each concept reads, keyed by relative file path.

    Paths are relative to ``concepts_dir``, e.g. ``sepsis/sepsis3.sql``.
    Raises ``ValueError`` if a concept reads a derived table that no file in
    ``concepts_dir`` creates.
    """
    concepts_dir = Path(concepts_dir)
    files = _concept_files(concepts_dir)

    dependencies = {}
    for table, relative in files.items():
        with open(concepts_dir / relative, encoding="utf-8-sig") as fp:
            parsed = sqlglot.parse_one(fp.read(), read="bigquery")
        reads = {
            t.name for t in parsed.find_all(exp.Table) if t.db == derived_schema
        }
        reads.discard(table)

        unknown = reads - files.keys()
        if unknown:
            raise ValueError(
                f"{relative} reads {derived_schema} tables that no concept "
                f"creates: {', '.join(sorted(unknown))}"
            )
        dependencies[relative] = {files[r] for r in reads}
    return dependencies


def concept_order(
        concepts_dir: Union[str, os.PathLike],
        derived_schema: str = "mimiciv_derived",
    ) -> List[List[str]]:
    """Group the concepts into stages that can be built one after another.

    Every concept comes in a later stage than the concepts it reads, so the
    concepts within a stage do not depend on each other. Each stage is
    sorted by path, which keeps the order stable.
    """
    sorter = TopologicalSorter(concept_dependencies(concepts_dir, derived_schema))
    try:
        sorter.prepare()
    except CycleError as e:
        cycle = " -> ".join(e.args[1])
        raise ValueError(f"Concepts depend on each other in a cycle: {cycle}") from e

    stages = []
    while sorter.is_active():
        ready = sorted(sorter.get_ready())
        stages.append(ready)
        sorter.done(*ready)
    return stages


def print_concept_order(
        concepts_dir: Union[str, os.PathLike],
        derived_schema: str = "mimiciv_derived",
    ):
    """Print the concept files in build order, one per line."""
    for stage in concept_order(concepts_dir, derived_schema):
        for path in stage:
            print(path)
