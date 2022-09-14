#!/usr/bin/python3 -tt
#
# Copyright (c) 2022, Adam Simpkins
#

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import amt.config


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "-c", "--config", default="~/.amt", help="The AMT configuration file"
    )
    ap.add_argument(
        "--account",
        default="default",
        help="The account name to use",
    )
    args = ap.parse_args()

    config = amt.config.load_config(args.config)
    account = getattr(config.accounts, args.account, None)
    if account is None:
        ap.error(f"no account named {args.account}")
    if account.auth != "xoauth2":
        ap.error("this account does not use OAuth 2")

    account.prepare_auth()
    token = account.oauth2_token()
    token_str = token.decode("utf-8")
    print(token_str)


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
