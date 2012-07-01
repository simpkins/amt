#!/usr/bin/python3 -tt
#
# Copyright (c) 2012, Adam Simpkins
#
import logging
import os
import ssl


def load_ca_certs(ctx):
    """
    Attempt to load the CA certificates.
    """
    # Widely used locations for CA certificate files
    well_known_ca_cert_locations = [
        # Ubuntu
        '/etc/ssl/certs/ca-certificates.crt',
        # RedHat
        '/etc/pki/tls/certs/ca-bundle.crt',
    ]
    # Load all of the above locations that we can find
    for path in well_known_ca_cert_locations:
        if os.path.exists(path):
            logging.debug('loading certs from %s', path)
            ctx.load_verify_locations(path)


def new_ctx():
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLSv1)
    load_ca_certs(ctx)
    ctx.verify_mode = ssl.CERT_REQUIRED

    return ctx
