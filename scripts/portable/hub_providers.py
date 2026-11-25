"""Hugging Face and ModelScope upload provider clients and configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any, Callable
import urllib.error
import urllib.request

VALID_REPO_TYPES = frozenset({"model", "dataset"})


@dataclass(frozen=True)
class UploadTargetConfig:
    """Configuration and credential status for one artifact hosting provider."""

    provider: str
    enabled: bool
    token: str
    repo_id: str
    repo_type: str = "model"

    def __post_init__(self) -> None:
        cleaned_type = str(self.repo_type or "model").strip().lower() or "model"
        if cleaned_type not in VALID_REPO_TYPES:
            raise ValueError(
                f"Invalid repo_type '{self.repo_type}' for {self.provider}; expected 'model' or 'dataset'."
            )
        object.__setattr__(self, "repo_type", cleaned_type)
        object.__setattr__(self, "token", str(self.token or "").strip())
        object.__setattr__(self, "repo_id", str(self.repo_id or "").strip())

    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.token and self.repo_id)

    def missing_reason(self) -> str:
        if not self.enabled:
            return f"{self.provider} upload disabled by workflow input."
        secret_name = "HF_TOKEN" if self.provider == "huggingface" else "MODELSCOPE_TOKEN"
        var_name = (
            "HF_PORTABLE_REPO_ID"
            if self.provider == "huggingface"
            else "MODELSCOPE_PORTABLE_REPO_ID"
        )
        missing: list[str] = []
        if not self.token:
            missing.append(f"Secret `{secret_name}`")
        if not self.repo_id:
            missing.append(f"Variable `{var_name}`")
        return f"Missing GitHub repository placeholder(s): {', '.join(missing)}."


ProviderUploadFn = Callable[[UploadTargetConfig, Path, str, str], str]
ProviderFetchFn = Callable[[UploadTargetConfig, str], str | None]


def build_remote_url(config: UploadTargetConfig, remote_path: str) -> str:
    """Construct the direct download URL for an uploaded file on HF or ModelScope."""
    clean_remote = remote_path.lstrip("/")
    if config.provider == "huggingface":
        prefix = "datasets/" if config.repo_type == "dataset" else ""
        return f"https://huggingface.co/{prefix}{config.repo_id}/resolve/main/{clean_remote}"
    if config.provider == "modelscope":
        kind_segment = "datasets" if config.repo_type == "dataset" else "models"
        return f"https://www.modelscope.cn/{kind_segment}/{config.repo_id}/resolve/master/{clean_remote}"
    raise ValueError(f"Unsupported provider: {config.provider}")


class _HuggingFaceClient:
    def __init__(self, config: UploadTargetConfig) -> None:
        from huggingface_hub import HfApi

        self._config = config
        self._api = HfApi(token=config.token)
        self._repo_ready = False

    def fetch_text(self, remote_path: str) -> str | None:
        from huggingface_hub import hf_hub_download
        try:
            from huggingface_hub.errors import (
                EntryNotFoundError,
                HfHubHTTPError,
                RepositoryNotFoundError,
            )
        except ImportError:
            from huggingface_hub.utils import (
                EntryNotFoundError,
                HfHubHTTPError,
                RepositoryNotFoundError,
            )

        with tempfile.TemporaryDirectory(prefix="shinsekai-hf-fetch-") as tmp_dir:
            try:
                local_file = hf_hub_download(
                    repo_id=self._config.repo_id,
                    filename=remote_path,
                    repo_type=self._config.repo_type,
                    token=self._config.token,
                    cache_dir=tmp_dir,
                    force_download=True,
                )
            except (EntryNotFoundError, RepositoryNotFoundError):
                return None
            except HfHubHTTPError as exc:
                response = getattr(exc, "response", None)
                if getattr(response, "status_code", None) == 404:
                    return None
                raise
            return Path(local_file).read_text(encoding="utf-8")

    def upload(self, local_path: Path, remote_path: str, commit_message: str) -> str:
        if not self._repo_ready:
            self._api.create_repo(
                repo_id=self._config.repo_id,
                repo_type=self._config.repo_type,
                exist_ok=True,
                token=self._config.token,
            )
            self._repo_ready = True
        self._api.upload_file(
            path_or_fileobj=str(local_path),
            path_in_repo=remote_path,
            repo_id=self._config.repo_id,
            repo_type=self._config.repo_type,
            commit_message=commit_message,
            token=self._config.token,
        )
        return build_remote_url(self._config, remote_path)


def _is_already_exists_error(exc: Exception) -> bool:
    """Return True when a remote hub exception reports that the repository already exists."""
    message = str(exc).lower()
    return any(marker in message for marker in ("exist", "已存在"))


class _ModelScopeClient:
    def __init__(self, config: UploadTargetConfig) -> None:
        try:
            from modelscope.hub.api import HubApi
        except ImportError:
            from modelscope_hub import HubApi  # type: ignore[no-redef]

        self._config = config
        self._api = HubApi()
        self._api.login(config.token)
        self._repo_ready = False

    def fetch_text(self, remote_path: str) -> str | None:
        url = build_remote_url(self._config, remote_path)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {self._config.token}",
                "Cache-Control": "no-cache",
                "User-Agent": "shinsekai-portable-publisher",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def _ensure_repo(self) -> None:
        if self._repo_ready:
            return
        create_repo = getattr(self._api, "create_repo", None)
        if callable(create_repo):
            try:
                create_repo(
                    repo_id=self._config.repo_id,
                    repo_type=self._config.repo_type,
                    exist_ok=True,
                )
            except TypeError:
                try:
                    create_repo(repo_id=self._config.repo_id, repo_type=self._config.repo_type)
                except Exception as exc:
                    if not _is_already_exists_error(exc):
                        raise
            except Exception as exc:
                if not _is_already_exists_error(exc):
                    raise
        self._repo_ready = True

    def upload(self, local_path: Path, remote_path: str, commit_message: str) -> str:
        self._ensure_repo()
        self._api.upload_file(
            repo_id=self._config.repo_id,
            path_or_fileobj=str(local_path),
            path_in_repo=remote_path,
            repo_type=self._config.repo_type,
            commit_message=commit_message,
        )
        return build_remote_url(self._config, remote_path)


def _get_or_create_client(
    clients: dict[tuple[str, str, str], Any],
    config: UploadTargetConfig,
) -> Any:
    key = (config.provider, config.repo_type, config.repo_id)
    client = clients.get(key)
    if client is None:
        if config.provider == "huggingface":
            client = _HuggingFaceClient(config)
        elif config.provider == "modelscope":
            client = _ModelScopeClient(config)
        else:
            raise ValueError(f"Unsupported upload provider: {config.provider}")
        clients[key] = client
    return client


def make_default_clients() -> tuple[ProviderUploadFn, ProviderFetchFn]:
    """Create stateful upload and fetch callables sharing authenticated HF/ModelScope clients."""
    clients: dict[tuple[str, str, str], Any] = {}

    def _upload(
        config: UploadTargetConfig,
        local_path: Path,
        remote_path: str,
        commit_message: str,
    ) -> str:
        return _get_or_create_client(clients, config).upload(local_path, remote_path, commit_message)

    def _fetch(config: UploadTargetConfig, remote_path: str) -> str | None:
        return _get_or_create_client(clients, config).fetch_text(remote_path)

    return _upload, _fetch


def make_default_upload_fn() -> ProviderUploadFn:
    """Create a stateful upload function that caches authenticated HF/ModelScope clients."""
    upload_fn, _fetch_fn = make_default_clients()
    return upload_fn


def make_default_fetch_fn() -> ProviderFetchFn:
    """Create a stateful remote file fetch function for HF/ModelScope clients."""
    _upload_fn, fetch_fn = make_default_clients()
    return fetch_fn
