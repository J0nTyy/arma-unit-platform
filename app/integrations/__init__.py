"""Integration boundaries for external systems.

Each subpackage owns all communication with one external system. The rest of
the application talks to these clients through their Python interfaces and
never makes raw HTTP calls itself.

Phase 1 ships interface stubs only — no integration is implemented yet.
"""
