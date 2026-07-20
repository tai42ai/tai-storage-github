"""GitHub-backed :class:`~tai42_contract.storage.Storage` provider.

Importing this package registers :class:`GithubStorage` as the active storage
provider — the ``@tai42_app.storage.register_storage`` decorator fires as an import
side-effect. Point a manifest's ``storage_module`` at ``tai42_storage_github`` to
load it; configure it through ``STORAGE_GITHUB_``-prefixed environment variables.
"""

from tai42_storage_github.storage import GithubStorage

__all__ = ["GithubStorage"]
