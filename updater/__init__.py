# -*- coding: utf-8 -*-
"""
updater/ — Auto-update via GitHub Releases (público ou privado).

Uso típico:
    from updater.check_update import check_for_update, apply_update
    info = check_for_update()
    if info and info["has_update"]:
        apply_update(info)
"""
from .check_update import (  # noqa: F401
    check_for_update,
    download_asset,
    apply_update,
    UpdateError,
)
