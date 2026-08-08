"""Background cleanup for stale session ledgers."""

import threading


class SessionJanitor:
    def __init__(self, store, retention_provider, interval_seconds=3600):
        if not callable(retention_provider):
            raise ValueError("retention_provider must be callable")
        self.store = store
        self.retention_provider = retention_provider
        self.interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._loop,
            name="SessionJanitor",
            daemon=True,
        )
        self._started = False

    def start(self):
        if not self._started:
            self._started = True
            self._thread.start()

    def stop(self):
        self._stop_event.set()

    def join(self, timeout=0.25):
        if self._started:
            self._thread.join(timeout=timeout)
            return not self._thread.is_alive()
        return True

    def run_once(self, include_active_incognito=False):
        retry = getattr(self.store, "retry_failed_deletions", None)
        retried = retry() if callable(retry) else []
        removed = self.store.cleanup(
            self.retention_provider(),
            include_active_incognito=include_active_incognito,
        )
        return list(dict.fromkeys([*retried, *removed]))

    def _loop(self):
        while not self._stop_event.wait(self.interval_seconds):
            self.run_once()
