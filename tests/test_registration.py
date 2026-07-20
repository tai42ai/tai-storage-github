"""Import side-effect registration + the settings surface."""

from __future__ import annotations

import pytest
from tai_contract.storage import Storage

from tai_storage_github import GithubStorage


def test_import_exposes_storage_provider():
    import tai_storage_github

    assert tai_storage_github.GithubStorage.__name__ == "GithubStorage"
    assert issubclass(tai_storage_github.GithubStorage, Storage)


def test_import_registers_provider_as_side_effect():
    # Importing the package must fire @tai_app.storage.register_storage on
    # GithubStorage; the fake facet records the class it was handed. This fails
    # if the registration decorator is dropped, not just if the class changes.
    import tai_storage_github
    from tests.conftest import _fake_app

    assert _fake_app.storage.registered is tai_storage_github.GithubStorage


def test_settings_env_prefix_is_storage_github():
    from tai_storage_github.settings import GithubStorageSettings

    assert GithubStorageSettings.model_config.get("env_prefix") == "STORAGE_GITHUB_"


def test_settings_accessor_is_cached():
    from tai_storage_github.settings import GithubStorageSettings, github_storage_settings

    first = github_storage_settings()
    assert isinstance(first, GithubStorageSettings)
    # ``settings_cache`` memoizes the zero-arg accessor.
    assert github_storage_settings() is first


def test_join_strips_empty_and_stray_slash_segments():
    from tai_storage_github.storage import _join

    assert _join("https://x/", "/a//b/") == "https://x/a/b"
    assert _join("https://x/", "") == "https://x"
    assert _join("https://x", "a/b") == "https://x/a/b"


# An unset owner/repo must surface as a config error naming the env var — before
# any URL is built or request sent — never as a 404 masquerading as a missing
# object.


async def test_unset_username_raises_config_error(client, settings):
    settings.username = None

    with pytest.raises(RuntimeError, match="STORAGE_GITHUB_USERNAME"):
        await GithubStorage().load("x.j2")

    client.get.assert_not_called()


async def test_unset_repo_raises_config_error(client, settings):
    settings.repo = None

    with pytest.raises(RuntimeError, match="STORAGE_GITHUB_REPO"):
        await GithubStorage().list()

    client.get.assert_not_called()


async def test_unset_username_and_repo_both_named(client, settings):
    settings.username = None
    settings.repo = None

    with pytest.raises(RuntimeError, match="STORAGE_GITHUB_USERNAME and STORAGE_GITHUB_REPO"):
        await GithubStorage().upload("x.j2", "content")

    client.get.assert_not_called()
    client.put.assert_not_called()
