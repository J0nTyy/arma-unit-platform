"""Arma 3 unit management platform.

Discord is the primary interface; the application itself is organised as
independent layers (bot -> services -> repositories -> database) so future
interfaces (HTTP API, web dashboard) can reuse the same business logic.
"""

__version__ = "0.11.1"
