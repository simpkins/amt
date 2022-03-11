#!/usr/bin/python3 -tt
#
# Copyright (c) 2022, Adam Simpkins
#
import argparse
import logging
from typing import Dict, List, Set

import amt.config
import amt.getpassword
from amt.config import Account


def set_password(account: Account) -> None:
    password = amt.config.get_password_input(account=account)
    amt.getpassword.set_password(
        user=account.user,
        server=account.server,
        port=account.port,
        protocol=account.protocol,
        password=password,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-c",
        "--config",
        metavar="CONFIG_DIR",
        default="~/.amt",
        help="The path to the configuration directory",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="count",
        default=1,
        help="Increase the verbosity",
    )
    parser.add_argument(
        "account",
        nargs="?",
        default="default",
        help="The name of the account to update",
    )

    args = parser.parse_args()

    log_format = "%(asctime)s [%(levelname)s] %(message)s"
    if args.verbose > 1:
        logging.basicConfig(level=logging.DEBUG, format=log_format)
    else:
        logging.basicConfig(level=logging.INFO, format=log_format)

    amt_config = amt.config.load_config(args.config, ["accounts"])

    account = getattr(amt_config.accounts, args.account, None)
    if account is None:
        parser.error(f"no account named {args.account!r}")
    set_password(account)
    print(
        f"Successfully updated password for {account.user} @ {account.server}"
    )


if __name__ == "__main__":
    main()
