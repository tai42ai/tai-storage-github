"""GitHub-backed :class:`~tai_contract.storage.Storage` provider.

Text lives on the render path (``load``/``list``/``upload``/``delete``/
``delete_dir``); binary/media rides ``load_bytes``/``upload_bytes`` (``stat``
inherits the contract's path-inference default — GitHub stores no per-object
content-type).

Reads go through the RAW endpoint (``raw.githubusercontent.com``), never the
Contents API: the Contents API silently returns ``content: ""`` for a file over
1 MiB, so reading a large object there would yield empty bytes. The raw endpoint
is CDN-cached, so a read shortly after a write may serve the previous content for
up to ~5 minutes. Writes go through the Contents API (base64) and are capped
conservatively well within the API limit, raising loudly before the request
rather than truncating.
"""

from __future__ import annotations

import base64
import logging

import httpx
from tai_contract.app import tai_app
from tai_contract.storage import Storage, assert_not_root

from tai_storage_github.client import GithubHttpxClient
from tai_storage_github.settings import GithubStorageSettings, github_storage_settings

logger = logging.getLogger(__name__)

RAW_BASE_URL = "https://raw.githubusercontent.com/{username}/{repo}/refs/heads/{branch}"
CONTENTS_API_URL = "https://api.github.com/repos/{username}/{repo}/contents"
TREES_API_URL = "https://api.github.com/repos/{username}/{repo}/git/trees/{branch}"

# Conservative upload cap, well within GitHub's Contents API limit. A file over
# this raises loudly BEFORE the request (never a silent truncation); the API's own
# 422 is the backstop for anything that slips through. Reads are NOT capped — they
# use the raw endpoint, which serves files of any size.
MAX_UPLOAD_BYTES = 1024 * 1024


def _join(base: str, path: str) -> str:
    """Join ``path`` onto ``base``, dropping empty and stray-slash segments."""
    joined = "/".join(segment for segment in path.split("/") if segment)
    base = base.rstrip("/")
    return f"{base}/{joined}" if joined else base


def _configured_settings() -> GithubStorageSettings:
    """The cached settings, raising a clear config error when the repo is unset.

    Checked at use time, before any URL is built, so a missing owner/repo
    surfaces as this message naming the env vars — never as a 404 on a URL with
    ``None`` formatted into it (which would masquerade as a missing object).
    """
    settings = github_storage_settings()
    missing = [
        env
        for env, value in (("STORAGE_GITHUB_USERNAME", settings.username), ("STORAGE_GITHUB_REPO", settings.repo))
        if not value
    ]
    if missing:
        raise RuntimeError(f"GitHub storage is not configured: set {' and '.join(missing)} to the target repository.")
    return settings


def _auth_headers(settings: GithubStorageSettings) -> dict[str, str]:
    """Authorization header, present only when a token is configured.

    The token is read from the :class:`~pydantic.SecretStr` solely here; it never
    appears in a log line or error message (only headers carry it, and headers are
    never logged).
    """
    if settings.token is None:
        return {}
    return {"Authorization": f"Bearer {settings.token.get_secret_value()}"}


def _api_headers(settings: GithubStorageSettings) -> dict[str, str]:
    return {
        **_auth_headers(settings),
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _raise_for_status(resp: httpx.Response, action: str, path: str, url: str) -> None:
    """Surface an HTTP error loudly; the log names the URL/status/body, never the token."""
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError:
        logger.error("HTTP error %s %s (%s): status=%s body=%s", action, path, url, resp.status_code, resp.text[:200])
        raise


# Importing this module registers GithubStorage as the active storage provider (a
# manifest's storage_module: tai_storage_github names this package to import; there
# is no entry-point). The decorator returns the class unchanged.
@tai_app.storage.register_storage
class GithubStorage(Storage):
    async def load(self, path: str) -> str:
        settings = _configured_settings()
        url = _join(RAW_BASE_URL.format(username=settings.username, repo=settings.repo, branch=settings.branch), path)
        async with tai_app.clients.client_ctx(GithubHttpxClient) as client:
            resp = await client.get(url, headers=_auth_headers(settings))
            self._guard_read(resp, path, url)
            return resp.text

    async def load_bytes(self, path: str) -> bytes:
        settings = _configured_settings()
        url = _join(RAW_BASE_URL.format(username=settings.username, repo=settings.repo, branch=settings.branch), path)
        async with tai_app.clients.client_ctx(GithubHttpxClient) as client:
            resp = await client.get(url, headers=_auth_headers(settings))
            self._guard_read(resp, path, url)
            # Raw bytes straight off the raw endpoint — no size cap, so a file over
            # 1 MiB (which the Contents API would return empty) reads in full.
            return resp.content

    @staticmethod
    def _guard_read(resp: httpx.Response, path: str, url: str) -> None:
        if resp.status_code == 404:
            raise FileNotFoundError(f"Object not found: {path}")
        _raise_for_status(resp, "loading", path, url)

    async def list(self) -> list[str]:
        return await self._list_blobs("")

    async def _list_blobs(self, prefix: str) -> list[str]:
        """Every blob path in the repo, optionally filtered to ``prefix``.

        Uses the recursive Git Trees API (one request) rather than the Contents
        API, whose per-directory listing caps at 1000 entries with no pagination —
        a large directory would be silently under-listed. The Trees response
        carries a ``truncated`` flag, raised on loudly rather than acting on a
        partial listing.
        """
        settings = _configured_settings()
        url = TREES_API_URL.format(username=settings.username, repo=settings.repo, branch=settings.branch)
        async with tai_app.clients.client_ctx(GithubHttpxClient) as client:
            resp = await client.get(url, headers=_api_headers(settings), params={"recursive": "1"})
            _raise_for_status(resp, "listing", prefix or "/", url)
            data = resp.json()
            if not isinstance(data, dict):
                raise RuntimeError(f"Expected a tree object from {url}, got {type(data).__name__}")
            if data.get("truncated"):
                raise RuntimeError(f"GitHub tree listing was truncated; the tree is too large to list safely: {url}")
            return [
                item["path"]
                for item in data.get("tree", [])
                if isinstance(item, dict)
                and item.get("type") == "blob"
                and (not prefix or item["path"].startswith(prefix))
            ]

    async def upload(self, path: str, content: str) -> None:
        await self._put_contents(path, content.encode("utf-8"))

    async def upload_bytes(self, path: str, data: bytes, content_type: str | None = None) -> None:
        # content_type is intentionally unused: GitHub keeps no per-object
        # content-type, so stat() infers it from the path suffix.
        await self._put_contents(path, data)

    async def _put_contents(self, path: str, data: bytes) -> None:
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError(
                f"Refusing to upload {len(data)} bytes to {path!r}: exceeds the conservative "
                f"{MAX_UPLOAD_BYTES}-byte GitHub Contents API upload cap. Store large objects elsewhere."
            )
        settings = _configured_settings()
        url = _join(CONTENTS_API_URL.format(username=settings.username, repo=settings.repo), path)
        headers = _api_headers(settings)
        encoded = base64.b64encode(data).decode("ascii")
        async with tai_app.clients.client_ctx(GithubHttpxClient) as client:
            sha: str | None = None
            # A 404 means the object does not exist yet (a create); any other
            # failure (auth, rate-limit) must surface, not be mistaken for a new
            # object.
            get_resp = await client.get(url, headers=headers, params={"ref": settings.branch})
            if get_resp.status_code == 200:
                existing = get_resp.json()
                if isinstance(existing, dict):
                    sha = existing.get("sha")
            elif get_resp.status_code != 404:
                _raise_for_status(get_resp, "resolving for upload", path, url)

            payload: dict[str, str] = {"message": f"Update {path}", "content": encoded, "branch": settings.branch}
            if sha:
                payload["sha"] = sha
            resp = await client.put(url, headers=headers, json=payload)
            # The 422 backstop: an oversize/invalid payload the API itself rejects.
            _raise_for_status(resp, "uploading", path, url)

    async def delete(self, path: str) -> None:
        settings = _configured_settings()
        url = _join(CONTENTS_API_URL.format(username=settings.username, repo=settings.repo), path)
        headers = _api_headers(settings)
        async with tai_app.clients.client_ctx(GithubHttpxClient) as client:
            get_resp = await client.get(url, headers=headers, params={"ref": settings.branch})
            if get_resp.status_code == 404:
                raise FileNotFoundError(f"Object not found: {path}")
            _raise_for_status(get_resp, "resolving for delete", path, url)

            data = get_resp.json()
            # The Contents API returns a list for a directory and an object for a
            # file; only a file has a deletable blob sha.
            if not isinstance(data, dict):
                raise FileNotFoundError(f"Object not found: {path}")

            sha = data.get("sha")
            # The delete payload requires the blob sha; a file object without one
            # is an unexpected API response, raised on here rather than deferred
            # to the remote's opaque 422.
            if not sha:
                raise RuntimeError(f"GitHub Contents API returned no blob sha for {path}; cannot delete it.")

            payload = {"message": f"Delete {path}", "sha": sha, "branch": settings.branch}
            resp = await client.request("DELETE", url, headers=headers, json=payload)
            _raise_for_status(resp, "deleting", path, url)

    async def delete_dir(self, path: str) -> None:
        """Delete every file under ``path``, one Contents-API request per file.

        GitHub has no bulk delete, so files are deleted sequentially. A failure
        mid-loop raises immediately and leaves the files already deleted gone —
        the partial state surfaces loudly rather than being hidden or rolled
        back.
        """
        assert_not_root(path)
        prefix = path if path.endswith("/") else f"{path}/"
        files = await self._list_blobs(prefix)
        if not files:
            raise FileNotFoundError(f"Directory not found or empty: {path}")

        for file_path in files:
            try:
                await self.delete(file_path)
            except FileNotFoundError:
                # The object was already gone (a concurrent delete). A folder
                # delete is idempotent: the goal is absence, and it holds. A real
                # DELETE failure raises HTTPStatusError and is not caught here, so
                # it still surfaces loudly.
                logger.info("Object %s already gone during dir delete of %s; skipping", file_path, path)


__all__ = ["GithubStorage"]
