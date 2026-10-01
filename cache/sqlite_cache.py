import sqlite3
from pathlib import Path

from jobfit.schemas.report import AnalysisReport


class SQLiteResultCache:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        if str(path) != ":memory:":
            self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS analysis_cache ("
                "cache_key TEXT PRIMARY KEY, report_json TEXT NOT NULL, "
                "created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )

    def get(self, key: str) -> AnalysisReport | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT report_json FROM analysis_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        return AnalysisReport.model_validate_json(row[0])

    def set(self, key: str, report: AnalysisReport) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO analysis_cache (cache_key, report_json) VALUES (?, ?) "
                "ON CONFLICT(cache_key) DO UPDATE SET "
                "report_json = excluded.report_json, "
                "created_at = CURRENT_TIMESTAMP",
                (key, report.model_dump_json()),
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=5.0)
