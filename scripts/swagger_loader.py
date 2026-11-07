"""Load and prepare Swagger data for test generation.

This module supports:
- loading Swagger from a URL or local file
- updating a local fallback copy
- extracting API routes and endpoint-specific contract details
"""

import json
import os
import pathlib
import urllib.request

DEFAULT_SWAGGER_PATH = pathlib.Path("swagger") / "spec.json"
DEFAULT_SWAGGER_URL = "http://localhost:8080/swagger.json"


def resolve_swagger_source(cli_swagger_source: str | None = None) -> str:
    """Resolve Swagger source from CLI value, env var, or default URL."""
    swagger_source = cli_swagger_source or os.getenv("SWAGGER_PATH")
    if swagger_source:
        return swagger_source

    return DEFAULT_SWAGGER_URL


def extract_schema_definitions(swagger_spec: dict) -> dict:
    """Return schema definitions for Swagger 2 or OpenAPI 3 docs."""
    definitions = swagger_spec.get("definitions")
    if isinstance(definitions, dict):
        return definitions

    components = swagger_spec.get("components", {})
    schemas = components.get("schemas", {}) if isinstance(components, dict) else {}
    return schemas if isinstance(schemas, dict) else {}


def load_swagger_spec_dict(swagger_source: str) -> dict:
    """Load Swagger JSON from a URL or local file path."""
    if swagger_source.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(swagger_source) as response:
                swagger_spec = json.loads(response.read().decode("utf-8"))
            update_local_swagger_cache(swagger_spec)
            return swagger_spec
        except Exception as error:
            if DEFAULT_SWAGGER_PATH.is_file():
                print(
                    f"Failed to fetch live Swagger from '{swagger_source}'. "
                    f"Falling back to local cache at '{DEFAULT_SWAGGER_PATH}'."
                )
                with open(DEFAULT_SWAGGER_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
            raise RuntimeError(
                f"Failed to fetch Swagger JSON from '{swagger_source}'."
            ) from error

    swagger_path = pathlib.Path(swagger_source)
    if not swagger_path.is_file():
        raise FileNotFoundError(
            f"Swagger file not found at '{swagger_path}'. "
            "Provide --swagger <path-or-url>, set SWAGGER_PATH, "
            f"or make '{DEFAULT_SWAGGER_URL}' reachable. "
            f"A local fallback file can also exist at '{DEFAULT_SWAGGER_PATH}'."
        )

    with open(swagger_path, "r", encoding="utf-8") as f:
        return json.load(f)


def update_local_swagger_cache(swagger_spec: dict) -> None:
    """Store the latest live Swagger response as a local fallback file."""
    DEFAULT_SWAGGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DEFAULT_SWAGGER_PATH, "w", encoding="utf-8") as f:
        json.dump(swagger_spec, f, indent=2)


def extract_api_endpoints(swagger_spec: dict) -> set[str]:
    """Return all Swagger paths that look like application API routes."""
    paths = swagger_spec.get("paths", {})
    return {
        path
        for path in paths.keys()
        if isinstance(path, str) and path.startswith("/api/")
    }


def extract_endpoint_spec(swagger_spec: dict, endpoint: str) -> dict:
    """Return the contract fragment needed to generate one endpoint test."""
    path_item = swagger_spec.get("paths", {}).get(endpoint)
    if not isinstance(path_item, dict):
        raise KeyError(f"Endpoint '{endpoint}' was not found in Swagger paths.")

    supported_methods = {
        method: details
        for method, details in path_item.items()
        if isinstance(details, dict)
    }

    if not supported_methods:
        raise ValueError(f"Endpoint '{endpoint}' does not define any methods in Swagger.")

    return {
        "endpoint": endpoint,
        "path": path_item,
        "definitions": extract_schema_definitions(swagger_spec),
        "methods": supported_methods,
    }


def extract_response_expectations(swagger_spec: dict, endpoint: str) -> dict:
    """Read the required POST happy-path contract, resolving local schema refs."""
    def resolve(value: dict, seen: tuple[str, ...] = ()) -> dict:
        if "$ref" not in value:
            return value
        ref = value["$ref"]
        if not ref.startswith("#/") or ref in seen:
            raise ValueError(f"Unsupported or cyclic Swagger reference: {ref}")
        target = swagger_spec
        for token in ref[2:].split("/"):
            target = target[token.replace("~1", "/").replace("~0", "~")]
        return resolve(target, (*seen, ref))

    def properties(schema: dict, ancestors: tuple[int, ...] = ()) -> dict:
        schema = resolve(schema)
        if id(schema) in ancestors:
            raise ValueError(f"Cyclic response schema for POST {endpoint}.")
        ancestors = (*ancestors, id(schema))
        result = dict(schema.get("properties", {}))
        for part in schema.get("allOf", []):
            result.update(properties(part, ancestors))
        return result

    operation = swagger_spec.get("paths", {}).get(endpoint, {}).get("post")
    if not isinstance(operation, dict):
        raise ValueError(f"Swagger must define POST {endpoint}.")
    responses = operation.get("responses", {})
    statuses = sorted(str(status) for status in responses if str(status).isdigit()
                      and 200 <= int(status) < 300)
    if len(statuses) != 1:
        raise ValueError(f"POST {endpoint} must define one unambiguous success response.")
    status = statuses[0]
    response = resolve(responses.get(status, responses.get(int(status))))
    schema = response.get("schema")
    if schema is None:
        schema = response.get("content", {}).get("application/json", {}).get("schema")
    if not isinstance(schema, dict):
        raise ValueError(f"POST {endpoint} {status} must define a JSON response schema.")
    fields = properties(schema)
    stable_names = ("success", "valid", "status", "message", "error")
    field_names = [name for name in stable_names if name in fields]
    if not field_names:
        raise ValueError(f"POST {endpoint} {status} has no supported stable response fields.")
    return {"endpoint": endpoint, "method": "post", "expected_status": int(status),
            "field_names": field_names, "response_schema": schema,
            "field_schemas": {name: resolve(fields[name]) for name in field_names}}
