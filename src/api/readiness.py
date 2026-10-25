"""Cached local readiness; no provider calls, file scans, inference or writes."""
import threading
import time
import sqlite3
from .database import read_snapshot


class Readiness:
    def __init__(self, settings, *, clock=time.monotonic, ttl=5):
        self.settings, self.clock, self.ttl = settings, clock, ttl
        self._lock = threading.Lock()
        self._until = 0
        self._result = None

    def check(self, identity_configured):
        with self._lock:
            now = self.clock()
            if self._result is not None and now < self._until and self._result['checks']['identity'] == ('configured' if identity_configured else 'unavailable'):
                return {**self._result, 'checks': dict(self._result['checks'])}
            database = 'unavailable'
            try:
                with read_snapshot(self.settings.operational_database) as db:
                    # Probe required columns using no-row SELECTs; no expensive scan.
                    db.execute('SELECT id,run_time,status,message FROM pipeline_runs LIMIT 0')
                    db.execute('SELECT id,check_time,check_name,status FROM data_quality_results LIMIT 0')
                database = 'available'
            except (sqlite3.Error, OSError, ValueError):
                pass
            ready = identity_configured and database == 'available'
            self._result = {'status': 'ready' if ready else 'not_ready',
                            'checks': {'identity': 'configured' if identity_configured else 'unavailable', 'operational_database': database},
                            'data_freshness': 'not_assessed', 'provider_connectivity': 'not_assessed'}
            self._until = now + self.ttl
            return {**self._result, 'checks': dict(self._result['checks'])}
