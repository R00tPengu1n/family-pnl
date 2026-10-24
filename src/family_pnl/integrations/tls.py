"""One TLS context for every outgoing HTTPS client of the process."""

import ssl
from functools import cache

import certifi


@cache
def tls_context() -> ssl.SSLContext:
    # Loading the CA bundle takes ~0.25 s; one context serves every client of the process.
    return ssl.create_default_context(cafile=certifi.where())
