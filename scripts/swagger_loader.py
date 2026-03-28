"""Load and prepare Swagger data for test generation.

This module supports:
- loading Swagger from a URL or local file
- updating a local fallback copy
- extracting API routes and endpoint-specific contract details

The generator may still apply runtime notes on top of this contract when the
real application behavior is known to differ from Swagger.
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
