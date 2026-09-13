"""The configuration core serves and applies, changed at runtime by device policy edits.

A change of ``network`` is only saved (docs/decisions.md, decision 9): it moves the address the
panel listens on and needs Compose profiles, so it applies at the next start of the box.
Until then every live edit applies with the network the box is running.

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
        self._saved: Config | None = None  # config.yaml with a network change not applied yet

    @property
    def config(self) -> Config:
        return self._config

    @property
    def saved(self) -> Config:
        """config.yaml as written: differs from ``config`` by a network waiting for a restart."""
        return self._saved or self._config

    @property
    def restart_required(self) -> bool:
        return self._saved is not None and self._saved.network != self._config.network

    def save(self, change: Change) -> Config:
        """Run ``change`` on config.yaml and apply nothing: for changes of the network itself."""
        with self._lock:
            config, _changed = change(self.path)
            self._saved = config if config.network != self._config.network else None
            return config

    def edit(self, change: Change) -> Config:
        """Run ``change`` on config.yaml and make the host follow; one edit at a time."""
        with self._lock:
            before = self.path.read_text(encoding="utf-8")
            written, changed = change(self.path)
            # a saved network change waits for the restart; the live edit keeps the running network
            config = written.model_copy(update={"network": self._config.network})
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
            if self._saved is not None:
                self._saved = written
            if self._watchers is not None:
                self._watchers.sync(uplinks)
            return config
