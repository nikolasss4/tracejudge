"""Eval suites: a YAML file with an agent reference, defaults, an optional judge and cases."""

from __future__ import annotations

import copy
import fnmatch
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from tracejudge.scorers.deterministic import build_scorers


class Criterion(BaseModel):
    name: str
    description: str
    # Optional pass/fail examples shown to the judge.
    examples: list[dict[str, Any]] = Field(default_factory=list)


class JudgeConfig(BaseModel):
    model: str = "claude-sonnet-5-5"
    criteria: list[Criterion] = Field(default_factory=list)
    instructions: str = ""
    fixtures: str | None = None
    # Apply every criterion to every case unless the case lists its own.
    default_all: bool = True


class Case(BaseModel):
    id: str
    input: Any
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    expect: dict[str, Any] = Field(default_factory=dict)
    # Judge criteria for this case: a list of names, true (all), or false (none).
    judge: list[str] | bool | None = None
    reference: str | None = None


class Suite(BaseModel):
    name: str
    description: str = ""
    agent: str | None = None
    repeats: int = 3
    defaults: dict[str, Any] = Field(default_factory=dict)
    judge: JudgeConfig | None = None
    cases: list[Case]
    path: str | None = None

    def case_expect(self, case: Case) -> dict[str, Any]:
        merged = copy.deepcopy(self.defaults.get("expect", {}))
        for key, value in case.expect.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
        return merged

    def judge_criteria(self, case: Case) -> list[Criterion]:
        if self.judge is None or case.judge is False:
            return []
        by_name = {c.name: c for c in self.judge.criteria}
        if isinstance(case.judge, list):
            unknown = [n for n in case.judge if n not in by_name]
            if unknown:
                raise ValueError(f"case {case.id}: unknown judge criteria {unknown}")
            return [by_name[n] for n in case.judge]
        if case.judge is True or self.judge.default_all:
            return list(self.judge.criteria)
        return []

    def select(self, patterns: list[str] | None) -> list[Case]:
        """Cases whose id or a tag matches any of the glob patterns (all cases if none)."""
        if not patterns:
            return list(self.cases)
        return [
            c for c in self.cases if any(fnmatch.fnmatch(c.id, p) or p in c.tags for p in patterns)
        ]


def load_suite(path: str | Path) -> Suite:
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    data.setdefault("name", path.stem)
    suite = Suite(**data, path=str(path))
    seen: set[str] = set()
    for case in suite.cases:
        if case.id in seen:
            raise ValueError(f"{path}: duplicate case id {case.id!r}")
        seen.add(case.id)
        build_scorers(suite.case_expect(case))  # validate expectations early
        suite.judge_criteria(case)
    return suite
