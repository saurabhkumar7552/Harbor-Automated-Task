"""Small strict JSON Schema subset used identically in prompts and validation."""
import json
import re
from .errors import ContractError


def string():
    return {"type": "string", "minLength": 1, "maxLength": 60000}


def array(items, minimum=1, maximum=64):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def obj(**properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


PROPOSAL = obj(
    task_id={"type": "string", "pattern": "^[a-z][a-z0-9]*(?:-[a-z0-9]+){1,7}$", "maxLength": 64},
    title=string(), domain=string(), learning_objective=string(), difficulty_rationale=string(),
    problem_statement=string(), starting_environment=string(),
    functional_requirements=array(string()), constraints=array(string()),
    acceptance_criteria=array(string()), solution_strategy=string(),
    deterministic_tests=array(string()), dependencies=array(string()), edge_cases=array(string()),
    output_manifest=array(obj(path=string(), purpose=string())),
)
REVIEW = obj(
    verdict={"type": "string", "enum": ["PASS", "FAIL"]},
    difficulty={"type": "string", "enum": ["easy", "medium", "hard"]},
    reasoning_complexity=string(), dependent_steps={"type": "integer", "minimum": 1, "maximum": 100},
    ambiguity_assessment=string(), complete={"type": "boolean"},
    solvable={"type": "boolean"}, solvability_assessment=string(),
    stem_relevant={"type": "boolean"}, stem_assessment=string(),
    tests_adequate={"type": "boolean"}, test_assessment=string(),
    defects=array(string(), 0), required_changes=array(string(), 0),
    findings=array(obj(category={"type": "string", "enum": ["correctness", "environment", "packaging", "tests", "security_leakage", "difficulty", "quality"]},
                        severity={"type": "string", "enum": ["blocking", "non_blocking"]},
                        finding=string(), evidence=string(), required_change=string()), 0),
)
IMPLEMENTATION = obj(
    instruction=string(), reference_python=string(), tests_python=string(),
    mutants=array(obj(name=string(), rationale=string(), code=string()), 3, 12),
    requirements_traceability=array(obj(requirement=string(), tests=array(string()))),
)
AUDIT = obj(
    verdict={"type": "string", "enum": ["PASS", "FAIL"]},
    specification_matches={"type": "boolean"}, no_ambiguity={"type": "boolean"},
    no_answer_leakage={"type": "boolean"}, tests_meaningful={"type": "boolean"},
    mutants_plausible={"type": "boolean"}, rationale=string(),
    defects=array(string(), 0), required_changes=array(string(), 0),
    findings=array(obj(category={"type": "string", "enum": ["correctness", "environment", "packaging", "tests", "security_leakage", "difficulty", "quality"]},
                        severity={"type": "string", "enum": ["blocking", "non_blocking"]},
                        finding=string(), evidence=string(), required_change=string()), 0),
)


def validate(value, schema, path="$"):
    types = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    kind = schema["type"]
    if type(value) is not types[kind]:
        raise ContractError(f"{path}: expected {kind}")
    if "enum" in schema and value not in schema["enum"]:
        raise ContractError(f"{path}: invalid enum")
    if kind == "object":
        if set(value) != set(schema["required"]):
            raise ContractError(f"{path}: missing or unexpected fields")
        for key, child in schema["properties"].items():
            validate(value[key], child, f"{path}.{key}")
    elif kind == "array":
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 100):
            raise ContractError(f"{path}: array length out of bounds")
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")
    elif kind == "string":
        if not schema.get("minLength", 1) <= len(value.strip()) <= schema.get("maxLength", 60000):
            raise ContractError(f"{path}: string length out of bounds")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise ContractError(f"{path}: invalid identifier")
    elif kind == "integer" and not schema.get("minimum", 0) <= value <= schema.get("maximum", 100):
        raise ContractError(f"{path}: integer out of bounds")
    return value


def loads(text):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ContractError("Duplicate JSON field")
            result[key] = value
        return result
    try:
        return json.loads(text, object_pairs_hook=unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(ContractError("Nonfinite JSON")))
    except (ValueError, RecursionError) as exc:
        raise ContractError("Expected one complete JSON document; no fences or prose") from exc
