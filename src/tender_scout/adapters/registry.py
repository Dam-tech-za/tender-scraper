"""Build enabled adapters from config/sources.yaml."""

from __future__ import annotations

import importlib
import logging
from typing import Any

from tender_scout.adapters.base import SourceAdapter
from tender_scout.config import load_sources

logger = logging.getLogger(__name__)


def load_adapters(sources_config: dict[str, Any] | None = None) -> list[SourceAdapter]:
    cfg = sources_config or load_sources()
    defaults = cfg.get("defaults") or {}
    adapters: list[SourceAdapter] = []
    for name, spec in (cfg.get("sources") or {}).items():
        if not spec.get("enabled", False) or not spec.get("adapter"):
            continue
        module_name, _, cls_name = spec["adapter"].partition(":")
        try:
            cls = getattr(importlib.import_module(module_name), cls_name)
            adapters.append(cls({**defaults, **spec, "name": name}))
        except Exception as exc:  # noqa: BLE001
            logger.error("Could not load adapter %s: %s", name, exc)
    return adapters
