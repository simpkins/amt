#!/usr/bin/python3 -tt
#
# Copyright (c) 2022, Adam Simpkins
#

from typing import Dict, List

import json
import secretstorage

try:
    import msal
except ImportError:
    msal = None


class TokenFetcher:
    def __init__(
        self, username: str, client_id: str, authority: str, scopes: List[str]
    ) -> None:
        if msal is None:
            raise Exception(
                "unable to import msal: "
                "OAuth 2 authentication is not available"
            )

        cache_attrs: Dict[str, str] = {
            "user": username,
            "client_id": client_id,
            "authority": authority,
        }
        token_cache = TokenCache(
            label="OAuth 2.0 Cache", attributes=cache_attrs
        )
        self._app = msal.PublicClientApplication(
            client_id=client_id, authority=authority, token_cache=token_cache
        )
        self._scopes = list(scopes)
        self._username = username

    def get_token(self) -> bytes:
        result = None
        accounts = self._app.get_accounts(username=self._username)
        if accounts:
            result = self._app.acquire_token_silent(
                self._scopes, account=accounts[0]
            )

        if result is None:
            result = self._app.acquire_token_interactive(
                self._scopes, login_hint=self._username
            )

        if "access_token" in result:
            token_str = result["access_token"]
            return token_str.encode("utf-8")

        err = result.get("error")
        err_desc = result.get("error_description")
        corr_id = result.get("correlation_id")
        raise Exception(f"error getting OAuth2 token: {err}; {err_desc}")


if msal is not None:

    class TokenCache(msal.TokenCache):
        def __init__(self, label: str, attributes: Dict[str, str]) -> None:
            super().__init__()
            self._label = label
            self._attributes = attributes
            self._dbus = secretstorage.dbus_init()
            self._collection = secretstorage.get_default_collection(self._dbus)

            item = self._get_item()
            if item is not None:
                data = item.get_secret()
                self._cache = json.loads(data.decode("utf-8"))

        def add(self, event, **kwargs):
            result = super().add(event, **kwargs)
            self._update_saved_state()
            return result

        def modify(self, credential_type, old_entry, new_key_value_pairs=None):
            result = super().modify(
                credential_type, old_entry, new_key_value_pairs
            )
            self._update_saved_state()
            return result

        def _update_saved_state(self) -> None:
            contents = json.dumps(self._cache, sort_keys=True, indent=2)
            data = contents.encode("utf-8")
            item = self._get_item()
            if item is None:
                item = self._collection.create_item(
                    self._label, self._attributes, secret=data
                )
            else:
                item.set_secret(data)

        def _get_item(self):
            items = list(self._collection.search_items(self._attributes))
            if not items:
                return None
            elif len(items) == 1:
                return items[0]

            raise PasswordError(
                "found multiple entries in secret storage for "
                f"OAuth 2 token cache {self._label}"
            )
