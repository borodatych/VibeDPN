"""The configuration core serves and applies, changed at runtime by device policy edits.

Device policies live in ``config.yaml`` like everything else. An edit writes the file, applies the
router in place and re-syncs the uplink watchers; when the router refuses the new configuration,
the previous file is put back and applied again, so the file and the host never disagree.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from vibedpn.api.uplink import UplinkWatchers
from vibedpn.atomic import write_like
from vibedpn.config import Config, Upstream
from vibedpn.engine.router import RouterError, apply_router

Apply = Callable[[Config], list[Upstream]]
Change = Callable[[Path], tuple[Config, bool]]


class BoxState:
    def __init__(
        self,
        config: Config,
        path: Path,
        *,
        apply: Apply = apply_router,
        watchers: UplinkWatchers | None = None,
    ) -> None:
        self._config = config
        self.path = path
        self._apply = apply
        self._watchers = watchers
        self._lock = threading.Lock()

    @property
    def config(self) -> Config:
        return self._config

    def edit(self, change: Change) -> Config:
        """Run ``change`` on config.yaml and make the host follow; one edit at a time."""
        with self._lock:
            before = self.path.read_text(encoding="utf-8")
            config, changed = change(self.path)
            if not changed:
                self._config = config
                return config
            try:
                uplinks = self._apply(config)
            except RouterError:
                write_like(self.path, before)
                with suppress(RouterError):
                    self._apply(self._config)
                raise
            self._config = config
            if self._watchers is not None:
                self._watchers.sync(uplinks)
            return config
