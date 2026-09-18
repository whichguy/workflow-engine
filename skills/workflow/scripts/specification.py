"""Validation and traceability rules for workflow specification v1.

This module deliberately has no dependency on the workflow kernel.  It validates
the authored specification sidecar and the contract packets carried by already
normalised runtime steps; the kernel remains responsible for scheduling and
completion.

``validate_contracts`` returns one entry per FR or NFR, shaped as::

    {
        "REQ-ID": {
            "scope": ["D1", ...],
            "implemented_by": ["step-id", ...],
            "verified_by": {"D1": ["step-id", ...], ...},
        },
    }

``scope`` is always the effective, explicit deliverable scope (so ``"all"``
has been expanded).  NFRs have an empty ``implemented_by`` list because only
deliverable steps implement FRs.  ``step_context`` returns the bounded packet
context needed by a host: the step contract fields, resolved deliverable and
FR entities, and every NFR applicable to the step's declared deliverables.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple


class SpecificationError(ValueError):
    """Raised when an authored specification or step contract is invalid."""


SPECIFICATION_VERSION = 1

_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.-]*\Z")
_SPECIFICATION_KEYS = {
    "version",
    "goal",
    "deliverables",
    "functional_requirements",
    "nfrs",
    "assumptions",
    "out_of_scope",
    "unresolved",
}
_REQUIRED_SPECIFICATION_KEYS = {
    "version",
    "goal",
    "deliverables",
    "functional_requirements",
    "nfrs",
}
_DELIVERABLE_KEYS = {"id", "description", "requirements"}
_FUNCTIONAL_REQUIREMENT_KEYS = {"id", "description", "acceptance"}
_NFR_KEYS = {"id", "description", "acceptance", "scope", "verification_stage"}
_REQUIRED_NFR_KEYS = _NFR_KEYS.difference({"verification_stage"})
_STEP_CONTRACT_KEYS = {
    "role",
    "deliverables",
    "requirements",
    "verifies",
    "ready_when",
    "done_when",
    "shared_reason",
}
_REQUIRED_STEP_CONTRACT_KEYS = _STEP_CONTRACT_KEYS.difference({"shared_reason"})
_ROLES = {"deliverable", "setup", "integration", "verification", "release"}

__all__ = [
    "SpecificationError",
    "validate_specification",
    "validate_contracts",
    "step_context",
]


def _field_names(values: Iterable[Any]) -> str:
    return ", ".join(sorted((repr(value) for value in values)))


def _require_object(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SpecificationError(f"{label} must be an object")
    return value


def _require_exact_keys(
    value: Any,
    *,
    label: str,
    allowed: Set[str],
    required: Set[str],
) -> Mapping[str, Any]:
    object_value = _require_object(value, label=label)
    unknown = set(object_value).difference(allowed)
    missing = required.difference(object_value)
    if unknown:
        raise SpecificationError(f"{label} contains unknown fields: {_field_names(unknown)}")
    if missing:
        raise SpecificationError(f"{label} is missing fields: {_field_names(missing)}")
    return object_value


def _require_list(value: Any, *, label: str, nonempty: bool = False) -> List[Any]:
    if not isinstance(value, list):
        raise SpecificationError(f"{label} must be an array")
    if nonempty and not value:
        raise SpecificationError(f"{label} must be a nonempty array")
    return value


def _require_string(value: Any, *, label: str, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise SpecificationError(f"{label} must be a string")
    if nonempty and not value.strip():
        raise SpecificationError(f"{label} must be nonempty")
    return value


def _require_id(value: Any, *, label: str) -> str:
    identifier = _require_string(value, label=label)
    if _ID.fullmatch(identifier) is None:
        raise SpecificationError(
            f"{label} must match [A-Za-z][A-Za-z0-9_.-]*"
        )
    return identifier


def _id_list(value: Any, *, label: str, nonempty: bool = False) -> List[str]:
    raw_items = _require_list(value, label=label, nonempty=nonempty)
    items = [_require_id(item, label=f"{label}[{index}]") for index, item in enumerate(raw_items)]
    if len(set(items)) != len(items):
        raise SpecificationError(f"{label} contains duplicate IDs")
    return items


def _text_list(
    value: Any,
    *,
    label: str,
    nonempty: bool,
    nonempty_items: bool,
) -> List[str]:
    raw_items = _require_list(value, label=label, nonempty=nonempty)
    return [
        _require_string(item, label=f"{label}[{index}]", nonempty=nonempty_items)
        for index, item in enumerate(raw_items)
    ]


def _normalise_deliverable(raw: Any, *, index: int) -> Dict[str, Any]:
    label = f"deliverables[{index}]"
    value = _require_exact_keys(
        raw,
        label=label,
        allowed=_DELIVERABLE_KEYS,
        required=_DELIVERABLE_KEYS,
    )
    return {
        "id": _require_id(value["id"], label=f"{label}.id"),
        "description": _require_string(value["description"], label=f"{label}.description"),
        "requirements": _id_list(
            value["requirements"], label=f"{label}.requirements", nonempty=True
        ),
    }


def _normalise_functional_requirement(raw: Any, *, index: int) -> Dict[str, Any]:
    label = f"functional_requirements[{index}]"
    value = _require_exact_keys(
        raw,
        label=label,
        allowed=_FUNCTIONAL_REQUIREMENT_KEYS,
        required=_FUNCTIONAL_REQUIREMENT_KEYS,
    )
    return {
        "id": _require_id(value["id"], label=f"{label}.id"),
        "description": _require_string(value["description"], label=f"{label}.description"),
        "acceptance": _text_list(
            value["acceptance"],
            label=f"{label}.acceptance",
            nonempty=True,
            nonempty_items=True,
        ),
    }


def _normalise_nfr(raw: Any, *, index: int) -> Dict[str, Any]:
    label = f"nfrs[{index}]"
    value = _require_exact_keys(
        raw,
        label=label,
        allowed=_NFR_KEYS,
        required=_REQUIRED_NFR_KEYS,
    )
    scope_raw = value["scope"]
    if scope_raw == "all":
        scope: Any = "all"
    else:
        scope = _id_list(scope_raw, label=f"{label}.scope", nonempty=True)
    normalised = {
        "id": _require_id(value["id"], label=f"{label}.id"),
        "description": _require_string(value["description"], label=f"{label}.description"),
        "acceptance": _text_list(
            value["acceptance"],
            label=f"{label}.acceptance",
            nonempty=True,
            nonempty_items=True,
        ),
        "scope": scope,
    }
    if "verification_stage" in value:
        stage = _require_string(
            value["verification_stage"], label=f"{label}.verification_stage"
        )
        if stage not in {"readiness", "outcome"}:
            raise SpecificationError(
                f"{label}.verification_stage must be 'readiness' or 'outcome'"
            )
        normalised["verification_stage"] = stage
    # Omission intentionally remains omitted in the frozen object.  It is
    # interpreted as outcome only when validating a setup verifier, so older
    # frozen v1 sidecars retain their exact shape and digest.
    return normalised


def validate_specification(raw: Any, *, goal: str | None = None) -> Dict[str, Any]:
    """Validate and canonicalise an authored specification v1.

    Values are copied but textual fields are never stripped or otherwise
    normalised.  When ``goal`` is supplied, it must match the authored goal
    exactly, including whitespace and line endings.
    """

    value = _require_exact_keys(
        raw,
        label="specification",
        allowed=_SPECIFICATION_KEYS,
        required=_REQUIRED_SPECIFICATION_KEYS,
    )
    version = value["version"]
    if type(version) is not int or version != SPECIFICATION_VERSION:
        raise SpecificationError(f"specification.version must be {SPECIFICATION_VERSION}")
    authored_goal = _require_string(value["goal"], label="specification.goal")
    if goal is not None:
        if not isinstance(goal, str):
            raise SpecificationError("goal must be a string when supplied")
        if goal != authored_goal:
            raise SpecificationError("specification.goal must exactly match the original goal")

    deliverables_raw = _require_list(
        value["deliverables"], label="specification.deliverables", nonempty=True
    )
    requirements_raw = _require_list(
        value["functional_requirements"],
        label="specification.functional_requirements",
        nonempty=True,
    )
    nfrs_raw = _require_list(value["nfrs"], label="specification.nfrs", nonempty=True)
    deliverables = [
        _normalise_deliverable(item, index=index)
        for index, item in enumerate(deliverables_raw)
    ]
    functional_requirements = [
        _normalise_functional_requirement(item, index=index)
        for index, item in enumerate(requirements_raw)
    ]
    nfrs = [_normalise_nfr(item, index=index) for index, item in enumerate(nfrs_raw)]

    categories: Tuple[Tuple[str, Sequence[Mapping[str, Any]]], ...] = (
        ("deliverable", deliverables),
        ("functional requirement", functional_requirements),
        ("NFR", nfrs),
    )
    seen_ids: Dict[str, str] = {}
    for category, entities in categories:
        for entity in entities:
            identifier = str(entity["id"])
            previous = seen_ids.get(identifier)
            if previous is not None:
                raise SpecificationError(
                    f"{category} ID {identifier!r} duplicates {previous} ID"
                )
            seen_ids[identifier] = category

    deliverable_ids = {str(item["id"]) for item in deliverables}
    requirement_ids = {str(item["id"]) for item in functional_requirements}
    requirement_owner: Dict[str, str] = {}
    for deliverable in deliverables:
        deliverable_id = str(deliverable["id"])
        for requirement_id in deliverable["requirements"]:
            if requirement_id not in requirement_ids:
                raise SpecificationError(
                    f"deliverable {deliverable_id!r} references unknown functional "
                    f"requirement {requirement_id!r}"
                )
            previous_owner = requirement_owner.get(requirement_id)
            if previous_owner is not None:
                raise SpecificationError(
                    f"functional requirement {requirement_id!r} belongs to both "
                    f"{previous_owner!r} and {deliverable_id!r}"
                )
            requirement_owner[requirement_id] = deliverable_id
    for requirement_id in requirement_ids:
        if requirement_id not in requirement_owner:
            raise SpecificationError(
                f"functional requirement {requirement_id!r} belongs to no deliverable"
            )

    for nfr in nfrs:
        if nfr["scope"] == "all":
            continue
        for deliverable_id in nfr["scope"]:
            if deliverable_id not in deliverable_ids:
                raise SpecificationError(
                    f"NFR {nfr['id']!r} scope references unknown deliverable "
                    f"{deliverable_id!r}"
                )

    assumptions = _text_list(
        value.get("assumptions", []),
        label="specification.assumptions",
        nonempty=False,
        nonempty_items=True,
    )
    out_of_scope = _text_list(
        value.get("out_of_scope", []),
        label="specification.out_of_scope",
        nonempty=False,
        nonempty_items=True,
    )
    unresolved = _require_list(value.get("unresolved", []), label="specification.unresolved")
    if unresolved:
        raise SpecificationError("specification.unresolved must be empty before acceptance")

    return {
        "version": SPECIFICATION_VERSION,
        "goal": authored_goal,
        "deliverables": deepcopy(deliverables),
        "functional_requirements": deepcopy(functional_requirements),
        "nfrs": deepcopy(nfrs),
        "assumptions": deepcopy(assumptions),
        "out_of_scope": deepcopy(out_of_scope),
        "unresolved": [],
    }


def _spec_indexes(
    spec: Any,
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, str]]:
    normalised = validate_specification(spec)
    deliverables = {item["id"]: item for item in normalised["deliverables"]}
    requirements = {item["id"]: item for item in normalised["functional_requirements"]}
    nfrs = {item["id"]: item for item in normalised["nfrs"]}
    owners: Dict[str, str] = {}
    for deliverable in normalised["deliverables"]:
        for requirement_id in deliverable["requirements"]:
            owners[requirement_id] = deliverable["id"]
    return normalised, deliverables, requirements, nfrs, owners


def _effective_nfr_scope(nfr: Mapping[str, Any], deliverable_ids: Sequence[str]) -> List[str]:
    scope = nfr["scope"]
    if scope == "all":
        return list(deliverable_ids)
    return list(scope)


def _normalise_step_contract(
    raw: Any,
    *,
    label: str,
    deliverables: Mapping[str, Mapping[str, Any]],
    requirements: Mapping[str, Mapping[str, Any]],
    nfrs: Mapping[str, Mapping[str, Any]],
    requirement_owners: Mapping[str, str],
) -> Dict[str, Any]:
    value = _require_exact_keys(
        raw,
        label=label,
        allowed=_STEP_CONTRACT_KEYS,
        required=_REQUIRED_STEP_CONTRACT_KEYS,
    )
    role = _require_string(value["role"], label=f"{label}.role")
    if role not in _ROLES:
        raise SpecificationError(f"{label}.role is unsupported: {role!r}")
    declared_deliverables = _id_list(
        value["deliverables"], label=f"{label}.deliverables", nonempty=True
    )
    unknown_deliverables = set(declared_deliverables).difference(deliverables)
    if unknown_deliverables:
        raise SpecificationError(
            f"{label}.deliverables references unknown IDs: {_field_names(unknown_deliverables)}"
        )
    referenced_requirements = _id_list(
        value["requirements"], label=f"{label}.requirements"
    )
    unknown_requirements = set(referenced_requirements).difference(requirements)
    if unknown_requirements:
        raise SpecificationError(
            f"{label}.requirements references unknown FR IDs: {_field_names(unknown_requirements)}"
        )
    verified = _id_list(value["verifies"], label=f"{label}.verifies")
    all_requirement_ids = set(requirements).union(nfrs)
    unknown_verified = set(verified).difference(all_requirement_ids)
    if unknown_verified:
        raise SpecificationError(
            f"{label}.verifies references unknown requirement IDs: "
            f"{_field_names(unknown_verified)}"
        )
    ready_when = _text_list(
        value["ready_when"],
        label=f"{label}.ready_when",
        nonempty=True,
        nonempty_items=True,
    )
    done_when = _text_list(
        value["done_when"],
        label=f"{label}.done_when",
        nonempty=True,
        nonempty_items=True,
    )
    if "shared_reason" in value:
        shared_reason = _require_string(
            value["shared_reason"], label=f"{label}.shared_reason", nonempty=False
        )
    else:
        shared_reason = ""

    if role == "deliverable":
        if len(declared_deliverables) != 1:
            raise SpecificationError(
                f"{label}.deliverable role must declare exactly one deliverable"
            )
        if not referenced_requirements:
            raise SpecificationError(
                f"{label}.deliverable role requires at least one functional requirement"
            )
        owner = declared_deliverables[0]
        for requirement_id in referenced_requirements:
            if requirement_owners[requirement_id] != owner:
                raise SpecificationError(
                    f"{label}.requirements must belong to deliverable {owner!r}"
                )
    else:
        if referenced_requirements:
            raise SpecificationError(
                f"{label}.requirements may be nonempty only for a deliverable role"
            )
        if not shared_reason.strip():
            raise SpecificationError(
                f"{label}.shared_reason is required for role {role!r}"
            )

    declared_set = set(declared_deliverables)
    delivery_order = list(deliverables)
    for requirement_id in verified:
        if requirement_id in requirements:
            owner = requirement_owners[requirement_id]
            if owner not in declared_set:
                raise SpecificationError(
                    f"{label}.verifies FR {requirement_id!r} outside its declared "
                    "deliverable scope"
                )
            continue
        nfr_scope = set(_effective_nfr_scope(nfrs[requirement_id], delivery_order))
        if not declared_set.intersection(nfr_scope):
            raise SpecificationError(
                f"{label}.verifies NFR {requirement_id!r} outside its declared "
                "deliverable scope"
            )

    return {
        "role": role,
        "deliverables": declared_deliverables,
        "requirements": referenced_requirements,
        "verifies": verified,
        "ready_when": ready_when,
        "done_when": done_when,
        "shared_reason": shared_reason,
    }


def _normalise_steps(
    steps: Any,
    *,
    deliverables: Mapping[str, Mapping[str, Any]],
    requirements: Mapping[str, Mapping[str, Any]],
    nfrs: Mapping[str, Mapping[str, Any]],
    requirement_owners: Mapping[str, str],
) -> List[Dict[str, Any]]:
    raw_steps = _require_list(steps, label="steps", nonempty=True)
    records: List[Dict[str, Any]] = []
    seen_ids: Set[str] = set()
    for index, raw_step in enumerate(raw_steps):
        label = f"steps[{index}]"
        step = _require_object(raw_step, label=label)
        if "id" not in step or "needs" not in step or "contract" not in step:
            raise SpecificationError(f"{label} requires id, needs, and contract")
        step_id = _require_id(step["id"], label=f"{label}.id")
        if step_id in seen_ids:
            raise SpecificationError(f"steps has duplicate ID {step_id!r}")
        seen_ids.add(step_id)
        records.append(
            {
                "id": step_id,
                "needs": _id_list(step["needs"], label=f"{label}.needs"),
                "contract": _normalise_step_contract(
                    step["contract"],
                    label=f"{label}.contract",
                    deliverables=deliverables,
                    requirements=requirements,
                    nfrs=nfrs,
                    requirement_owners=requirement_owners,
                ),
            }
        )

    ids = {record["id"] for record in records}
    for record in records:
        unknown_needs = set(record["needs"]).difference(ids)
        if unknown_needs:
            raise SpecificationError(
                f"step {record['id']!r} needs unknown step IDs: {_field_names(unknown_needs)}"
            )
        if record["id"] in record["needs"]:
            raise SpecificationError(f"step {record['id']!r} cannot need itself")
    _assert_acyclic(records)
    return records


def _assert_acyclic(steps: Sequence[Mapping[str, Any]]) -> None:
    pending = {step["id"]: set(step["needs"]) for step in steps}
    while pending:
        ready = [step_id for step_id, needs in pending.items() if not needs]
        if not ready:
            raise SpecificationError("step dependency graph contains a cycle")
        for step_id in ready:
            del pending[step_id]
        completed = set(ready)
        for needs in pending.values():
            needs.difference_update(completed)


def _descendants(steps: Sequence[Mapping[str, Any]]) -> Dict[str, Set[str]]:
    children: Dict[str, Set[str]] = {step["id"]: set() for step in steps}
    for step in steps:
        for dependency in step["needs"]:
            children[dependency].add(step["id"])
    result: Dict[str, Set[str]] = {}
    for step_id in children:
        descendants: Set[str] = set()
        pending = list(children[step_id])
        while pending:
            child = pending.pop()
            if child in descendants:
                continue
            descendants.add(child)
            pending.extend(children[child])
        result[step_id] = descendants
    return result


def _same_or_descendant(
    candidate: str, prerequisite: str, descendants: Mapping[str, Set[str]]
) -> bool:
    return candidate == prerequisite or candidate in descendants[prerequisite]


def validate_contracts(spec: Any, steps: Any) -> Dict[str, Dict[str, Any]]:
    """Validate step contracts against ``spec`` and return coverage by requirement.

    ``steps`` must already be runtime-normalised enough to contain an ``id``, a
    complete ``needs`` list, and a nested ``contract`` object.  This function
    still rejects duplicate or unknown dependencies and cycles defensively; it
    does not change edges or select scheduling policy.
    """

    (
        normalised_spec,
        deliverables,
        requirements,
        nfrs,
        requirement_owners,
    ) = _spec_indexes(spec)
    records = _normalise_steps(
        steps,
        deliverables=deliverables,
        requirements=requirements,
        nfrs=nfrs,
        requirement_owners=requirement_owners,
    )
    by_step_id = {record["id"]: record for record in records}
    delivery_order = [item["id"] for item in normalised_spec["deliverables"]]
    descendants = _descendants(records)

    implementers_by_delivery: Dict[str, List[str]] = {
        deliverable_id: [] for deliverable_id in delivery_order
    }
    implementers_by_requirement: Dict[str, List[str]] = {
        requirement_id: [] for requirement_id in requirements
    }
    fr_verifiers: Dict[str, List[str]] = {requirement_id: [] for requirement_id in requirements}
    nfr_verifiers: Dict[str, Dict[str, List[str]]] = {
        nfr_id: {
            deliverable_id: []
            for deliverable_id in _effective_nfr_scope(nfr, delivery_order)
        }
        for nfr_id, nfr in nfrs.items()
    }

    for record in records:
        step_id = record["id"]
        contract = record["contract"]
        if contract["role"] == "deliverable":
            deliverable_id = contract["deliverables"][0]
            implementers_by_delivery[deliverable_id].append(step_id)
            for requirement_id in contract["requirements"]:
                implementers_by_requirement[requirement_id].append(step_id)
        for requirement_id in contract["verifies"]:
            if requirement_id in requirements:
                fr_verifiers[requirement_id].append(step_id)
                continue
            nfr_scope = set(_effective_nfr_scope(nfrs[requirement_id], delivery_order))
            for deliverable_id in contract["deliverables"]:
                if deliverable_id in nfr_scope:
                    nfr_verifiers[requirement_id][deliverable_id].append(step_id)

    for requirement_id, implementers in implementers_by_requirement.items():
        if not implementers:
            raise SpecificationError(
                f"functional requirement {requirement_id!r} has no deliverable implementer"
            )

    for record in records:
        step_id = record["id"]
        contract = record["contract"]
        if contract["role"] == "setup":
            for deliverable_id in contract["deliverables"]:
                for implementation_id in implementers_by_delivery[deliverable_id]:
                    if implementation_id not in descendants[step_id]:
                        raise SpecificationError(
                            f"setup step {step_id!r} must be an ancestor of deliverable "
                            f"implementer {implementation_id!r}"
                        )
        if contract["role"] in {"integration", "release"}:
            for deliverable_id in contract["deliverables"]:
                for implementation_id in implementers_by_delivery[deliverable_id]:
                    if step_id not in descendants[implementation_id]:
                        raise SpecificationError(
                            f"{contract['role']} step {step_id!r} must depend on "
                            f"deliverable implementer {implementation_id!r}"
                        )

    for requirement_id, verifier_ids in fr_verifiers.items():
        if not verifier_ids:
            raise SpecificationError(
                f"functional requirement {requirement_id!r} has no verifier"
            )
        for verifier_id in verifier_ids:
            for implementation_id in implementers_by_requirement[requirement_id]:
                if not _same_or_descendant(verifier_id, implementation_id, descendants):
                    raise SpecificationError(
                        f"FR verifier {verifier_id!r} is not an implementer or descendant "
                        f"of {implementation_id!r} for {requirement_id!r}"
                    )

    for nfr_id, nfr in nfrs.items():
        for deliverable_id in _effective_nfr_scope(nfr, delivery_order):
            verifier_ids = nfr_verifiers[nfr_id][deliverable_id]
            if not verifier_ids:
                raise SpecificationError(
                    f"NFR {nfr_id!r} lacks verifier coverage for deliverable "
                    f"{deliverable_id!r}"
                )
            for verifier_id in verifier_ids:
                verifier = by_step_id[verifier_id]
                if verifier["contract"]["role"] == "setup":
                    if nfr.get("verification_stage") != "readiness":
                        raise SpecificationError(
                            f"setup step {verifier_id!r} may verify NFR {nfr_id!r} "
                            "only when verification_stage is explicitly 'readiness'"
                        )
                    # The setup-ancestor check above permits the explicitly
                    # scoped readiness NFR before implementation starts.
                    continue
                for implementation_id in implementers_by_delivery[deliverable_id]:
                    if not _same_or_descendant(verifier_id, implementation_id, descendants):
                        raise SpecificationError(
                            f"NFR verifier {verifier_id!r} is not an implementer or "
                            f"descendant of {implementation_id!r} for {nfr_id!r}"
                        )

    coverage: Dict[str, Dict[str, Any]] = {}
    for requirement_id in requirements:
        owner = requirement_owners[requirement_id]
        coverage[requirement_id] = {
            "scope": [owner],
            "implemented_by": list(implementers_by_requirement[requirement_id]),
            "verified_by": {owner: list(fr_verifiers[requirement_id])},
        }
    for nfr_id, nfr in nfrs.items():
        scope = _effective_nfr_scope(nfr, delivery_order)
        coverage[nfr_id] = {
            "scope": scope,
            "implemented_by": [],
            "verified_by": {
                deliverable_id: list(nfr_verifiers[nfr_id][deliverable_id])
                for deliverable_id in scope
            },
        }
    return coverage


def step_context(spec: Any, step: Any) -> Dict[str, Any]:
    """Resolve the bounded specification context relevant to one runtime step.

    The return value contains ``step_id``, direct contract fields
    (``role``, ``requirements``, ``verifies``, ``ready_when``, ``done_when``,
    and ``shared_reason``), full declared deliverables and every FR entity
    owned by their scope, and every NFR whose effective scope intersects the
    declared deliverables.  It
    intentionally does not claim semantic truth of those assertions.
    """

    (
        normalised_spec,
        deliverables,
        requirements,
        nfrs,
        requirement_owners,
    ) = _spec_indexes(spec)
    value = _require_object(step, label="step")
    if "id" not in value or "contract" not in value:
        raise SpecificationError("step requires id and contract")
    step_id = _require_id(value["id"], label="step.id")
    contract = _normalise_step_contract(
        value["contract"],
        label="step.contract",
        deliverables=deliverables,
        requirements=requirements,
        nfrs=nfrs,
        requirement_owners=requirement_owners,
    )
    declared_deliverables = set(contract["deliverables"])
    delivery_order = [item["id"] for item in normalised_spec["deliverables"]]
    applicable_frs = [
        requirement
        for requirement in normalised_spec["functional_requirements"]
        if requirement_owners[requirement["id"]] in declared_deliverables
    ]
    applicable_nfrs = [
        nfr
        for nfr in normalised_spec["nfrs"]
        if declared_deliverables.intersection(_effective_nfr_scope(nfr, delivery_order))
    ]
    return {
        "step_id": step_id,
        "role": contract["role"],
        "deliverables": [
            deepcopy(deliverables[deliverable_id])
            for deliverable_id in contract["deliverables"]
        ],
        "requirements": list(contract["requirements"]),
        "verifies": list(contract["verifies"]),
        "functional_requirements": deepcopy(applicable_frs),
        "nfrs": deepcopy(applicable_nfrs),
        "ready_when": list(contract["ready_when"]),
        "done_when": list(contract["done_when"]),
        "shared_reason": contract["shared_reason"],
    }
