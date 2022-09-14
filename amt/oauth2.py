#!/usr/bin/python3 -tt
#
# Copyright (c) 2022, Adam Simpkins
#

from typing import List


class TokenFetcher:
    def __init__(
        self, username: str, client_id: str, authority: str, scopes: List[str]
    ) -> None:
        try:
            from msal import PublicClientApplication
        except ImportError:
            raise Exception(
                "unable to import msal: "
                "OAuth 2 authentication is not available"
            )

        self._app = PublicClientApplication(
            client_id=client_id, authority=authority
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
