"""Argus Labs Engine (Python package name kept as `roboforge`)."""

from roboforge.config import load_environment

# Load before agents and sponsor clients read their startup configuration.
load_environment()
