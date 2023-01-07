#!/usr/bin/env python3

from setuptools import setup
from kio_server import version

setup(
    name="kio-server",
    version=version.__version__,
    description="Kio Server",
    author="Alix",
    author_email="alix@politeauthority.io",
    url="https://github.com/politeauthority/kio",
    packages=[
        "kio_server",
        "kio_server.config",
        "kio_server.controllers",
        "kio_server.collections",
        "kio_server.models",
        "kio_server.utils",
    ],
)

# End File: kio/src/setup.py
