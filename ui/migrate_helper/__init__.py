"""Helpers for guiding users from the legacy Qt UI to the frontend UI."""

from __future__ import annotations

__all__ = ["MigrationRoleDialog", "show_migration_role_dialog"]


def __getattr__(name: str):
    if name in __all__:
        from ui.migrate_helper.dialog import (
            MigrationRoleDialog,
            show_migration_role_dialog,
        )

        values = {
            "MigrationRoleDialog": MigrationRoleDialog,
            "show_migration_role_dialog": show_migration_role_dialog,
        }
        return values[name]
    raise AttributeError(name)
