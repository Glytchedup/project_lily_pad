"""Keep the repository's tools namespace visible during pytest's package discovery."""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
