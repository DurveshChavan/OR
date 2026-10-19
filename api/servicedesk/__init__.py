"""The service desk of the service desk application.

This package is the SLA-aware dispatch application described in
`SCE/docs/FINAL_IMPLEMENTATION.md`. The Operations Research engine
(`api/engine/`, served by `api/main.py`) is separate and holds no state of
this application's; the one import across the line is
`services/hardware.py` calling `api/engine/replacement.py`, so the
replacement arithmetic has a single definition.
"""
