# V1.5.1

Typing hotfix for VS Code/Pylance.

- `load_config()` now returns `dict[str, Any]` instead of an unparameterized `dict`.
- `load_evidence_registry()` explicitly accepts a registry path, `Path`, full config mapping, or `None`.
- `_registry_path()` is typed consistently.
- This removes the false Pylance warning when `vscode_runner.py` calls `load_evidence_registry(cfg)`.
- Runtime behavior is unchanged.
