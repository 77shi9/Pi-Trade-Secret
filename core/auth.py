"""MSAL authentication for s3scope.

Generalized from the previous project's best-tested auth asset
(group_expansion.TokenSession): silent-first acquisition with a single
interactive fallback per scope set, one cached token per token audience
(Graph vs SharePoint site resource), atomic token-cache file writes, and a
strict no-second-login rule after a failure. MSAL results are never logged
because they can contain credentials.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import msal

LOGGER = logging.getLogger("s3scope.auth")

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT_ID = "14d82eec-204b-4c2f-b7e8-296a70dab67e"  # Microsoft Graph PowerShell public client
DEFAULT_TENANT_ID = "organizations"
DEFAULT_CACHE_PATH = BASE_DIR / ".cache" / "msal_cache.bin"
SHAREPOINT_HOST_SUFFIX = ".sharepoint.com"


class AuthenticationError(RuntimeError):
    """Token acquisition failed for the requested scopes."""


def scopes_for_url(url: str, graph_scopes: tuple[str, ...] = ("Sites.Read.All",)) -> list[str]:
    """Return the scopes matching a URL's token audience.

    SharePoint REST endpoints reject Graph-audience tokens, so
    ``*.sharepoint.com`` URLs use a site-resource token
    (``https://<host>/.default``) while Graph URLs use the Graph scopes.
    """
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith(SHAREPOINT_HOST_SUFFIX):
        return [f"https://{host}/.default"]
    return list(graph_scopes)


def decode_token_claims(access_token: str) -> dict:
    """Decode a JWT payload without verification (diagnostics only)."""
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


class TokenSession:
    """Silent-first MSAL session with one interactive fallback per scope set."""

    def __init__(
        self,
        client_id: str | None = None,
        tenant_id: str | None = None,
        *,
        cache_path: str | Path | None = None,
        graph_scopes: tuple[str, ...] = ("Sites.Read.All",),
    ) -> None:
        self.client_id = client_id or os.environ.get("MSAL_CLIENT_ID") or DEFAULT_CLIENT_ID
        self.tenant_id = tenant_id or os.environ.get("MSAL_TENANT_ID") or DEFAULT_TENANT_ID
        self.cache_path = Path(cache_path) if cache_path else DEFAULT_CACHE_PATH
        self.graph_scopes = tuple(graph_scopes)
        self._app: msal.PublicClientApplication | None = None
        self._cache: msal.SerializableTokenCache | None = None
        self._tokens: dict[tuple[str, ...], str] = {}
        self._accounts: dict[tuple[str, ...], object] = {}
        self._attempted: set[tuple[str, ...]] = set()
        self._failures: dict[tuple[str, ...], Exception] = {}

    # -- application and cache --------------------------------------------------

    def _application(self) -> msal.PublicClientApplication:
        if self._app is None:
            self._cache = msal.SerializableTokenCache()
            if self.cache_path.exists():
                LOGGER.info("[AUTH] Loading token cache: %s", self.cache_path)
                self._cache.deserialize(self.cache_path.read_text(encoding="utf-8"))
            else:
                LOGGER.info("[AUTH] No token cache found; starting clean.")
            self._app = msal.PublicClientApplication(
                self.client_id,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}",
                token_cache=self._cache,
            )
        return self._app

    def _save_cache(self) -> None:
        if self._cache is None:
            return
        serialized = self._cache.serialize()
        if not serialized:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.cache_path.parent,
                prefix="msal_cache_",
                suffix=".tmp",
                delete=False,
            ) as cache_file:
                temporary = Path(cache_file.name)
                cache_file.write(serialized)
            temporary.replace(self.cache_path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    # -- acquisition ---------------------------------------------------------------

    def get_token(self, scopes: list[str] | tuple[str, ...] | None = None) -> str:
        """Silent-first acquisition; one interactive fallback; cached thereafter."""
        wanted = tuple(scopes) if scopes else self.graph_scopes
        if wanted in self._tokens:
            return self._tokens[wanted]
        if wanted in self._attempted:
            raise AuthenticationError(
                "Authentication already failed for these scopes; no second login is allowed."
            ) from self._failures.get(wanted)
        self._attempted.add(wanted)
        try:
            token, account = self._acquire(list(wanted), allow_interactive=True)
        except Exception as error:
            self._failures[wanted] = error
            raise
        self._tokens[wanted] = token
        self._accounts[wanted] = account
        return token

    def refresh(self, scopes: list[str] | tuple[str, ...] | None = None) -> str:
        """Force one silent renewal; never opens a browser."""
        wanted = tuple(scopes) if scopes else self.graph_scopes
        token, account = self._acquire(list(wanted), allow_interactive=False, force_refresh=True)
        self._tokens[wanted] = token
        self._accounts[wanted] = account
        return token

    def get_token_for_url(self, url: str) -> str:
        return self.get_token(scopes_for_url(url, self.graph_scopes))

    def refresh_for_url(self, url: str) -> str:
        return self.refresh(scopes_for_url(url, self.graph_scopes))

    def claims_for(self, scopes: list[str] | tuple[str, ...] | None = None) -> dict:
        """Decoded claims of the cached token for these scopes (diagnostics)."""
        return decode_token_claims(self.get_token(scopes))

    def _acquire(
        self, scopes: list[str], *, allow_interactive: bool, force_refresh: bool = False
    ) -> tuple[str, object | None]:
        app = self._application()
        result = None
        LOGGER.info("[AUTH] Attempting silent authentication (scopes=%s)...", scopes)
        for account in app.get_accounts() or [None]:
            result = app.acquire_token_silent(scopes, account=account, force_refresh=force_refresh)
            if not (result and result.get("access_token")):
                result = None
                continue
            break
        if result is None and allow_interactive:
            LOGGER.info("[AUTH] Silent authentication failed; launching interactive login...")
            result = app.acquire_token_interactive(scopes=scopes)
        if not (result and result.get("access_token")):
            # The MSAL result itself is never logged: it can contain credentials.
            error = result.get("error", "no_token") if isinstance(result, dict) else "no_token"
            raise AuthenticationError(f"Microsoft authentication failed ({error}).")
        self._save_cache()
        claims = decode_token_claims(result["access_token"])
        username = claims.get("upn") or claims.get("preferred_username")
        account = None
        for candidate in app.get_accounts() or []:
            if username and str(candidate.get("username", "")).casefold() == str(username).casefold():
                account = candidate
                break
        LOGGER.info("[AUTH] Token acquired (audience=%s, user=%s).", claims.get("aud"), username)
        return result["access_token"], account
