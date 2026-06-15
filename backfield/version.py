"""Single source of truth for the package version (SemVer).

pyproject.toml reads this dynamically, so this is the ONE place to bump. On release:
bump here, add a dated section to CHANGELOG.md, commit, and tag ``v<version>``.
"""

__version__ = "0.2.0"
