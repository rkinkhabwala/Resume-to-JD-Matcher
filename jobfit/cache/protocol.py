from typing import Protocol

from jobfit.schemas.report import AnalysisReport


class ResultCache(Protocol):
    def get(self, key: str) -> AnalysisReport | None: ...

    def set(self, key: str, report: AnalysisReport) -> None: ...
