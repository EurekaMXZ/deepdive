from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from backend.ids import new_uuid7


DEFAULT_ENV_FILE_NAME = ".env"
ENV_FILE_ENV_VAR = "DEEPDIVE_ENV_FILE"
DEFAULT_CONFIG_VERSION = "repository-analysis-config-v1"


@dataclass(frozen=True)
class OpenAIConfig:
    model: str = "gpt-5.5"
    reasoning_effort: str = "medium"
    reasoning_summary: str = "auto"
    service_tier: str = "fast"
    parallel_tool_calls: bool = False
    use_previous_response_id: bool = False
    show_reasoning_summary: bool = True


@dataclass(frozen=True)
class PromptConfig:
    system_instruction_file: str = "prompts/system.md"
    developer_instruction_file: str = "prompts/developer.md"
    compaction_instruction_file: str = "prompts/compact.md"
    system_instruction: str | None = None
    developer_instruction: str | None = None
    compaction_instruction: str | None = None


@dataclass(frozen=True)
class AnalysisProfileConfig:
    goal_file: str
    max_turns: int
    max_tool_calls: int
    auto_compact_threshold_tokens: int
    goal: str | None = None


@dataclass(frozen=True)
class AnalysisConfig:
    default_profile: str = "repository_architecture_review"
    profiles: dict[str, AnalysisProfileConfig] = field(
        default_factory=lambda: {
            "repository_architecture_review": AnalysisProfileConfig(
                goal_file="profiles/repository_architecture_review.md",
                max_turns=80,
                max_tool_calls=200,
                auto_compact_threshold_tokens=120_000,
            )
        }
    )


@dataclass(frozen=True)
class ReadFileToolConfig:
    default_lines: int = 200
    max_lines: int = 500
    max_bytes: int = 65_536


@dataclass(frozen=True)
class SearchTextToolConfig:
    max_results: int = 100
    timeout_seconds: int = 20
    max_output_bytes: int = 1_048_576


@dataclass(frozen=True)
class ToolsConfig:
    enabled: tuple[str, ...] = ("list_files", "search_file", "search_text", "read_file")
    read_file: ReadFileToolConfig = field(default_factory=ReadFileToolConfig)
    search_text: SearchTextToolConfig = field(default_factory=SearchTextToolConfig)


@dataclass(frozen=True)
class SnapshotConfig:
    max_file_bytes: int = 1_048_576
    max_git_bundle_bytes: int = 536_870_912
    lfs_policy: str = "pointer_only"
    submodule_policy: str = "record_only"
    binary_policy: str = "metadata_only"


@dataclass(frozen=True)
class CacheConfig:
    root_dir: str = "/cache/deepdive"
    max_worker_cache_bytes: int = 53_687_091_200
    max_prefix_bytes: int = 2_147_483_648
    ttl_days: int = 7
    min_free_disk_percent: int = 15


@dataclass(frozen=True)
class AppConfig:
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    prompt: PromptConfig = field(default_factory=PromptConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    snapshot: SnapshotConfig = field(default_factory=SnapshotConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)

    @classmethod
    def default(cls) -> "AppConfig":
        return cls()

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConfigSnapshot:
    id: object
    config_version: str
    content_hash: str
    config_json: dict[str, Any]


def load_dotenv_if_exists(env_file: str | os.PathLike[str] | None = None) -> bool:
    path = _resolve_env_file(env_file)
    if not path.is_file():
        return False

    for line in path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)

    return True


def load_app_config_from_env() -> AppConfig:
    load_dotenv_if_exists()
    default = AppConfig.default()
    default_profile = os.environ.get("ANALYSIS_DEFAULT_PROFILE", default.analysis.default_profile)
    default_profile_config = default.analysis.profiles[default.analysis.default_profile]
    profile_config = AnalysisProfileConfig(
        goal_file=os.environ.get("ANALYSIS_GOAL_FILE", default_profile_config.goal_file),
        max_turns=_int_env("ANALYSIS_MAX_TURNS", default_profile_config.max_turns),
        max_tool_calls=_int_env("ANALYSIS_MAX_TOOL_CALLS", default_profile_config.max_tool_calls),
        auto_compact_threshold_tokens=_int_env(
            "ANALYSIS_AUTO_COMPACT_THRESHOLD_TOKENS",
            default_profile_config.auto_compact_threshold_tokens,
        ),
        goal=os.environ.get("ANALYSIS_GOAL") or _read_optional_text_file(
            os.environ.get("ANALYSIS_GOAL_FILE", default_profile_config.goal_file)
        ),
    )
    return AppConfig(
        openai=OpenAIConfig(
            model=os.environ.get("OPENAI_MODEL", default.openai.model),
            reasoning_effort=os.environ.get("OPENAI_REASONING_EFFORT", default.openai.reasoning_effort),
            reasoning_summary=os.environ.get("OPENAI_REASONING_SUMMARY", default.openai.reasoning_summary),
            service_tier=os.environ.get("OPENAI_SERVICE_TIER", default.openai.service_tier),
            parallel_tool_calls=False,
            use_previous_response_id=_bool_env(os.environ.get("OPENAI_USE_PREVIOUS_RESPONSE_ID", str(default.openai.use_previous_response_id))),
            show_reasoning_summary=_bool_env(
                os.environ.get("API_SHOW_MODEL_REASONING_SUMMARY", str(default.openai.show_reasoning_summary))
            ),
        ),
        prompt=PromptConfig(
            system_instruction_file=os.environ.get("PROMPT_SYSTEM_INSTRUCTION_FILE", default.prompt.system_instruction_file),
            developer_instruction_file=os.environ.get("PROMPT_DEVELOPER_INSTRUCTION_FILE", default.prompt.developer_instruction_file),
            compaction_instruction_file=os.environ.get("PROMPT_COMPACTION_INSTRUCTION_FILE", default.prompt.compaction_instruction_file),
            system_instruction=os.environ.get("PROMPT_SYSTEM_INSTRUCTION") or _read_optional_text_file(
                os.environ.get("PROMPT_SYSTEM_INSTRUCTION_FILE", default.prompt.system_instruction_file)
            ),
            developer_instruction=os.environ.get("PROMPT_DEVELOPER_INSTRUCTION") or _read_optional_text_file(
                os.environ.get("PROMPT_DEVELOPER_INSTRUCTION_FILE", default.prompt.developer_instruction_file)
            ),
            compaction_instruction=os.environ.get("PROMPT_COMPACTION_INSTRUCTION") or _read_optional_text_file(
                os.environ.get("PROMPT_COMPACTION_INSTRUCTION_FILE", default.prompt.compaction_instruction_file)
            ),
        ),
        analysis=AnalysisConfig(
            default_profile=default_profile,
            profiles={default_profile: profile_config},
        ),
        tools=ToolsConfig(
            enabled=_csv_env("TOOLS_ENABLED", default.tools.enabled),
            read_file=ReadFileToolConfig(
                default_lines=_int_env("TOOL_READ_FILE_DEFAULT_LINES", default.tools.read_file.default_lines),
                max_lines=_int_env("TOOL_READ_FILE_MAX_LINES", default.tools.read_file.max_lines),
                max_bytes=_int_env("TOOL_READ_FILE_MAX_BYTES", default.tools.read_file.max_bytes),
            ),
            search_text=SearchTextToolConfig(
                max_results=_int_env("TOOL_SEARCH_TEXT_MAX_RESULTS", default.tools.search_text.max_results),
                timeout_seconds=_int_env("TOOL_SEARCH_TEXT_TIMEOUT_SECONDS", default.tools.search_text.timeout_seconds),
                max_output_bytes=_int_env("TOOL_SEARCH_TEXT_MAX_OUTPUT_BYTES", default.tools.search_text.max_output_bytes),
            ),
        ),
        snapshot=SnapshotConfig(
            max_file_bytes=_int_env("SNAPSHOT_MAX_FILE_BYTES", default.snapshot.max_file_bytes),
            max_git_bundle_bytes=_int_env("SNAPSHOT_MAX_GIT_BUNDLE_BYTES", default.snapshot.max_git_bundle_bytes),
            lfs_policy=os.environ.get("SNAPSHOT_LFS_POLICY", default.snapshot.lfs_policy),
            submodule_policy=os.environ.get("SNAPSHOT_SUBMODULE_POLICY", default.snapshot.submodule_policy),
            binary_policy=os.environ.get("SNAPSHOT_BINARY_POLICY", default.snapshot.binary_policy),
        ),
        cache=CacheConfig(
            root_dir=os.environ.get("CACHE_ROOT_DIR", default.cache.root_dir),
            max_worker_cache_bytes=_int_env("CACHE_MAX_WORKER_CACHE_BYTES", default.cache.max_worker_cache_bytes),
            max_prefix_bytes=_int_env("CACHE_MAX_PREFIX_BYTES", default.cache.max_prefix_bytes),
            ttl_days=_int_env("CACHE_TTL_DAYS", default.cache.ttl_days),
            min_free_disk_percent=_int_env("CACHE_MIN_FREE_DISK_PERCENT", default.cache.min_free_disk_percent),
        ),
    )


def _resolve_env_file(env_file: str | os.PathLike[str] | None) -> Path:
    if env_file is not None:
        return Path(env_file)
    configured_path = os.environ.get(ENV_FILE_ENV_VAR)
    if configured_path:
        return Path(configured_path)
    return Path.cwd() / DEFAULT_ENV_FILE_NAME


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]

    return key, value


def _bool_env(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return int(value)


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if value is None:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


def _read_optional_text_file(path_value: str) -> str | None:
    path = Path(path_value)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def app_config_from_json(config_json: dict[str, Any] | None) -> AppConfig:
    if not isinstance(config_json, dict):
        return AppConfig.default()

    default = AppConfig.default()
    openai_json = _section(config_json, "openai")
    prompt_json = _section(config_json, "prompt")
    analysis_json = _section(config_json, "analysis")
    tools_json = _section(config_json, "tools")
    snapshot_json = _section(config_json, "snapshot")
    cache_json = _section(config_json, "cache")

    default_profile = str(analysis_json.get("default_profile") or default.analysis.default_profile)
    profile_defaults = default.analysis.profiles[default.analysis.default_profile]
    profiles_json = analysis_json.get("profiles")
    selected_profile_json = {}
    if isinstance(profiles_json, dict):
        selected_profile_json = profiles_json.get(default_profile) if isinstance(profiles_json.get(default_profile), dict) else {}

    profile_config = AnalysisProfileConfig(
        goal_file=str(selected_profile_json.get("goal_file") or profile_defaults.goal_file),
        max_turns=_int_value(selected_profile_json.get("max_turns"), profile_defaults.max_turns),
        max_tool_calls=_int_value(selected_profile_json.get("max_tool_calls"), profile_defaults.max_tool_calls),
        auto_compact_threshold_tokens=_int_value(
            selected_profile_json.get("auto_compact_threshold_tokens"),
            profile_defaults.auto_compact_threshold_tokens,
        ),
        goal=_optional_str(selected_profile_json.get("goal")),
    )

    read_file_json = _nested_section(tools_json, "read_file")
    search_text_json = _nested_section(tools_json, "search_text")

    return AppConfig(
        openai=OpenAIConfig(
            model=str(openai_json.get("model") or default.openai.model),
            reasoning_effort=str(openai_json.get("reasoning_effort") or default.openai.reasoning_effort),
            reasoning_summary=str(openai_json.get("reasoning_summary") or default.openai.reasoning_summary),
            service_tier=str(openai_json.get("service_tier") or default.openai.service_tier),
            parallel_tool_calls=False,
            use_previous_response_id=_bool_value(openai_json.get("use_previous_response_id"), default.openai.use_previous_response_id),
            show_reasoning_summary=_bool_value(
                openai_json.get("show_reasoning_summary"),
                default.openai.show_reasoning_summary,
            ),
        ),
        prompt=PromptConfig(
            system_instruction_file=str(prompt_json.get("system_instruction_file") or default.prompt.system_instruction_file),
            developer_instruction_file=str(prompt_json.get("developer_instruction_file") or default.prompt.developer_instruction_file),
            compaction_instruction_file=str(prompt_json.get("compaction_instruction_file") or default.prompt.compaction_instruction_file),
            system_instruction=_optional_str(prompt_json.get("system_instruction")),
            developer_instruction=_optional_str(prompt_json.get("developer_instruction")),
            compaction_instruction=_optional_str(prompt_json.get("compaction_instruction")),
        ),
        analysis=AnalysisConfig(
            default_profile=default_profile,
            profiles={default_profile: profile_config},
        ),
        tools=ToolsConfig(
            enabled=_tuple_value(tools_json.get("enabled"), default.tools.enabled),
            read_file=ReadFileToolConfig(
                default_lines=_int_value(read_file_json.get("default_lines"), default.tools.read_file.default_lines),
                max_lines=_int_value(read_file_json.get("max_lines"), default.tools.read_file.max_lines),
                max_bytes=_int_value(read_file_json.get("max_bytes"), default.tools.read_file.max_bytes),
            ),
            search_text=SearchTextToolConfig(
                max_results=_int_value(search_text_json.get("max_results"), default.tools.search_text.max_results),
                timeout_seconds=_int_value(search_text_json.get("timeout_seconds"), default.tools.search_text.timeout_seconds),
                max_output_bytes=_int_value(search_text_json.get("max_output_bytes"), default.tools.search_text.max_output_bytes),
            ),
        ),
        snapshot=SnapshotConfig(
            max_file_bytes=_int_value(snapshot_json.get("max_file_bytes"), default.snapshot.max_file_bytes),
            max_git_bundle_bytes=_int_value(snapshot_json.get("max_git_bundle_bytes"), default.snapshot.max_git_bundle_bytes),
            lfs_policy=str(snapshot_json.get("lfs_policy") or default.snapshot.lfs_policy),
            submodule_policy=str(snapshot_json.get("submodule_policy") or default.snapshot.submodule_policy),
            binary_policy=str(snapshot_json.get("binary_policy") or default.snapshot.binary_policy),
        ),
        cache=CacheConfig(
            root_dir=str(cache_json.get("root_dir") or default.cache.root_dir),
            max_worker_cache_bytes=_int_value(cache_json.get("max_worker_cache_bytes"), default.cache.max_worker_cache_bytes),
            max_prefix_bytes=_int_value(cache_json.get("max_prefix_bytes"), default.cache.max_prefix_bytes),
            ttl_days=_int_value(cache_json.get("ttl_days"), default.cache.ttl_days),
            min_free_disk_percent=_int_value(cache_json.get("min_free_disk_percent"), default.cache.min_free_disk_percent),
        ),
    )


def _section(config_json: dict[str, Any], name: str) -> dict[str, Any]:
    value = config_json.get(name)
    return value if isinstance(value, dict) else {}


def _nested_section(parent: dict[str, Any], name: str) -> dict[str, Any]:
    value = parent.get(name)
    return value if isinstance(value, dict) else {}


def _int_value(value: Any, default: int) -> int:
    if value is None:
        return default
    return int(value)


def _bool_value(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return _bool_env(str(value))


def _tuple_value(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip()) or default
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip()) or default
    return default


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def create_config_snapshot(config: AppConfig, config_version: str = DEFAULT_CONFIG_VERSION) -> ConfigSnapshot:
    config_json = config.to_json_dict()
    encoded = json.dumps(config_json, sort_keys=True, separators=(",", ":")).encode()
    return ConfigSnapshot(
        id=new_uuid7(),
        config_version=config_version,
        content_hash="sha256:" + hashlib.sha256(encoded).hexdigest(),
        config_json=config_json,
    )
