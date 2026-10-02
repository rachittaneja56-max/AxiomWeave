"""Server-owned source membership roles and their deterministic authority policy."""

from dataclasses import dataclass
from typing import Literal

SourceRole = Literal["PRIMARY", "SUPPORTING", "STYLE", "REFERENCE", "OPERATOR_CONTEXT"]


@dataclass(frozen=True, slots=True)
class SourceRolePolicy:
    may_ground_facts: bool
    may_contextualize: bool
    controls_presentation: bool
    factual_by_default: bool
    controls_task: bool
    conflict_requires_review: bool


_ROLE_POLICIES: dict[SourceRole, SourceRolePolicy] = {
    "PRIMARY": SourceRolePolicy(
        may_ground_facts=True,
        may_contextualize=True,
        controls_presentation=False,
        factual_by_default=True,
        controls_task=False,
        conflict_requires_review=False,
    ),
    "SUPPORTING": SourceRolePolicy(
        may_ground_facts=True,
        may_contextualize=True,
        controls_presentation=False,
        factual_by_default=True,
        controls_task=False,
        conflict_requires_review=True,
    ),
    "STYLE": SourceRolePolicy(
        may_ground_facts=False,
        may_contextualize=False,
        controls_presentation=True,
        factual_by_default=False,
        controls_task=False,
        conflict_requires_review=False,
    ),
    "REFERENCE": SourceRolePolicy(
        may_ground_facts=False,
        may_contextualize=True,
        controls_presentation=False,
        factual_by_default=False,
        controls_task=False,
        conflict_requires_review=False,
    ),
    "OPERATOR_CONTEXT": SourceRolePolicy(
        may_ground_facts=False,
        may_contextualize=False,
        controls_presentation=False,
        factual_by_default=False,
        controls_task=True,
        conflict_requires_review=False,
    ),
}


def validate_source_role(value: str) -> SourceRole:
    if value not in _ROLE_POLICIES:
        raise ValueError("Source membership role is invalid")
    return value  # type: ignore[return-value]


def source_role_policy(value: str) -> SourceRolePolicy:
    return _ROLE_POLICIES[validate_source_role(value)]
