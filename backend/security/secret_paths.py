from __future__ import annotations

from fnmatch import fnmatchcase

SECRET_PATH_POLICY_VERSION = "secret-paths-v4"

SAFE_ENV_TEMPLATE_NAMES = {
    ".env.defaults",
    ".env.example",
    ".env.sample",
    ".env.template",
}

SECRET_PATH_NAMES = {
    ".env",
    ".env.local",
    ".env.development",
    ".env.production",
    ".git-credentials",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "credentials",
    "credentials.json",
    "service-account.json",
    "service-account-key.json",
    "secrets.json",
    "secrets.yaml",
    "secrets.yml",
    "secret.json",
    "secret.yaml",
    "secret.yml",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}

SECRET_PATH_PARTS = {
    ".git",
    ".ssh",
    ".aws",
    ".azure",
    ".gcp",
}

SECRET_PATH_PREFIXES = {
    ".config/gcloud",
    ".docker",
}

SECRET_PATH_GLOBS = (
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*credentials*.json",
    "*service-account*.json",
    "*secret*.json",
    "*secret*.yaml",
    "*secret*.yml",
    "*secrets*.json",
    "*secrets*.yaml",
    "*secrets*.yml",
)


def visible_path_sql(*, path_column: str = "path", name_column: str = "name") -> str:
    return f"""
                      {path_column} <> '.git'
                      AND {path_column} NOT LIKE '.git/%'
                      AND {path_column} <> '.env'
                      AND {path_column} <> '.env.local'
                      AND {path_column} <> '.env.development'
                      AND {path_column} <> '.env.production'
                      AND (
                          lower({name_column}) NOT LIKE '.env.%'
                          OR lower({name_column}) IN (
                              '.env.defaults',
                              '.env.example',
                              '.env.sample',
                              '.env.template'
                          )
                      )
                      AND {path_column} <> '.git-credentials'
                      AND {path_column} <> '.npmrc'
                      AND {path_column} <> '.pypirc'
                      AND {path_column} <> '.netrc'
                      AND lower({name_column}) NOT IN (
                          'credentials',
                          'credentials.json',
                          'service-account.json',
                          'service-account-key.json',
                          'secrets.json',
                          'secrets.yaml',
                          'secrets.yml',
                          'secret.json',
                          'secret.yaml',
                          'secret.yml',
                          'id_rsa',
                          'id_dsa',
                          'id_ecdsa',
                          'id_ed25519'
                      )
                      AND lower({path_column}) NOT LIKE '%.pem'
                      AND lower({path_column}) NOT LIKE '%.key'
                      AND lower({path_column}) NOT LIKE '%.p12'
                      AND lower({path_column}) NOT LIKE '%.pfx'
                      AND lower({path_column}) NOT LIKE '%credentials%.json'
                      AND lower({path_column}) NOT LIKE '%service-account%.json'
                      AND lower({path_column}) NOT LIKE '%secret%.json'
                      AND lower({path_column}) NOT LIKE '%secret%.yaml'
                      AND lower({path_column}) NOT LIKE '%secret%.yml'
                      AND lower({path_column}) NOT LIKE '%secrets%.json'
                      AND lower({path_column}) NOT LIKE '%secrets%.yaml'
                      AND lower({path_column}) NOT LIKE '%secrets%.yml'
                      AND lower({path_column}) NOT LIKE '.ssh/%'
                      AND lower({path_column}) NOT LIKE '%.ssh/%'
                      AND lower({path_column}) NOT LIKE '.aws/%'
                      AND lower({path_column}) NOT LIKE '%.aws/%'
                      AND lower({path_column}) NOT LIKE '.azure/%'
                      AND lower({path_column}) NOT LIKE '%.azure/%'
                      AND lower({path_column}) NOT LIKE '.gcp/%'
                      AND lower({path_column}) NOT LIKE '%.gcp/%'
                      AND lower({path_column}) NOT LIKE '.docker/%'
                      AND lower({path_column}) NOT LIKE '%.docker/%'
                      AND lower({path_column}) NOT LIKE '.config/gcloud/%'
                      AND lower({path_column}) NOT LIKE '%.config/gcloud/%'
    """


def is_secret_path(path: str) -> bool:
    normalized = _normalize_path_pattern(path)
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return False
    lower_parts = [part.lower() for part in parts]
    name = lower_parts[-1]
    if name in SAFE_ENV_TEMPLATE_NAMES:
        return False
    if name in SECRET_PATH_NAMES:
        return True
    if name.startswith(".env."):
        return True
    if any(part in SECRET_PATH_PARTS for part in lower_parts):
        return True
    joined = "/".join(lower_parts)
    if any(joined == prefix or joined.startswith(prefix + "/") for prefix in SECRET_PATH_PREFIXES):
        return True
    return any(_matches_secret_glob(joined, glob) for glob in SECRET_PATH_GLOBS)


def _normalize_path_pattern(path: str) -> str:
    normalized = path.replace("\\", "/").strip().strip("/")
    while normalized.startswith("**/"):
        normalized = normalized[3:]
    normalized = normalized.replace("/**/", "/")
    return normalized


def _matches_secret_glob(path: str, pattern: str) -> bool:
    if fnmatchcase(path, pattern):
        return True
    return fnmatchcase(path.rsplit("/", 1)[-1], pattern)
