"""Load and validate the small, explicit JSON Schema subset used by this project."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def technology():
    return read_json(ROOT / "technology/java-1.21.1.json")


def validate_schema(value, schema, location="$", errors=None):
    """Validate this repository's schema subset, not arbitrary JSON Schema files."""
    if errors is None:
        errors = []
    supported = {"$schema", "title", "type", "additionalProperties", "required", "properties",
                 "const", "enum", "pattern", "minLength", "minItems", "maxItems", "items"}
    unknown = set(schema) - supported
    if unknown:
        errors.append(f"{location}: unsupported schema keywords: {sorted(unknown)}")
    expected_type = schema.get("type")
    types = {"object": dict, "array": list, "string": str}
    if expected_type and not isinstance(value, types[expected_type]):
        errors.append(f"{location}: expected {expected_type}")
        return errors
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        errors.append(f"{location}: must equal {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{location}: invalid value {value!r}")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{location}: missing {key}")
        for key, item in value.items():
            if key in properties:
                validate_schema(item, properties[key], f"{location}.{key}", errors)
            elif schema.get("additionalProperties") is False:
                errors.append(f"{location}: unknown property {key}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{location}: empty string")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{location}: invalid identifier {value!r}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", float("inf")):
            errors.append(f"{location}: invalid number of items")
        for index, item in enumerate(value):
            validate_schema(item, schema.get("items", {}), f"{location}[{index}]", errors)
    return errors


def validate_project():
    from .fixtures import SUITES, cases
    errors = []
    schema = read_json(ROOT / "schema/component.schema.json")
    fixture_ids = {case["id"] for case in cases()}
    known_ids = set()
    for path in sorted((ROOT / "components").glob("*.json")):
        component = read_json(path)
        validate_schema(component, schema, path.name, errors)
        cid = component.get("id")
        if cid in known_ids:
            errors.append(f"Duplicate component id: {cid}")
        known_ids.add(cid)
        if component.get("technology") != technology()["id"]:
            errors.append(f"{path.name}: technology mismatch")
        ports = component.get("ports", [])
        names = [port.get("name") for port in ports if isinstance(port, dict)]
        if len(names) != len(set(names)):
            errors.append(f"{path.name}: duplicate port names")
        for fixture in component.get("evidence", {}).get("fixtures", []):
            if fixture not in fixture_ids:
                errors.append(f"{path.name}: unknown fixture {fixture}")
        for suite in component.get("evidence", {}).get("fixture_suites", []):
            if suite not in SUITES:
                errors.append(f"{path.name}: unknown fixture suite {suite}")
        for reference in component.get("evidence", {}).get("characterizations", []):
            try:
                from .characterize import build_contract, sha256
                target = (ROOT / reference["path"]).resolve()
                if not target.is_relative_to((ROOT / "characterizations").resolve()):
                    raise ValueError("Characterization path escapes its directory")
                if sha256(target) != reference["sha256"]:
                    raise ValueError("Characterization digest differs")
                characterization = read_json(target)
                if characterization["component"] != cid or characterization["technology"] != component["technology"]:
                    raise ValueError("Characterization component or technology differs")
                builder = build_contract
                if characterization.get("id") == "repeater_coverage_v2":
                    from .characterize_broad import build_broad_contract
                    builder = build_broad_contract
                if cid != "repeater" or characterization != builder([item["run"] for item in characterization["evidence"]]):
                    raise ValueError("Characterization differs from current evidence reanalysis")
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append(f"{path.name}: invalid characterization: {error}")
        for reference in component.get("evidence", {}).get("executable_models", []):
            try:
                from .model_validation import build_model_contract, sha
                target = (ROOT / reference["path"]).resolve()
                if not target.is_relative_to((ROOT / "models").resolve()):
                    raise ValueError("Executable model path escapes its directory")
                model = read_json(target)
                if sha(target) != reference["sha256"]:
                    raise ValueError("Executable model digest differs")
                if model["component"] != cid or model["technology"] != component["technology"]:
                    raise ValueError("Executable model component/technology differs")
                if cid != "repeater" or model != build_model_contract([e["run"] for e in model["evidence"]], model["event_evidence"]["run"]):
                    raise ValueError("Executable model differs from current implementation or evidence reanalysis")
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append(f"{path.name}: invalid executable model: {error}")
    if not known_ids:
        errors.append("No component contracts found")
    from .cells import validate_cells
    errors.extend(validate_cells())
    from .connections import validate_connections
    errors.extend(validate_connections())
    if (ROOT/"validation/mapping/release.json").exists():
        from tools.check_mapping_release import validate
        errors.extend(validate())
    return errors
