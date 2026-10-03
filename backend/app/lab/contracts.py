"""Contratti condivisi del laboratorio di verita (SP1)."""

from __future__ import annotations

from typing import Literal

DataMode = Literal["REAL", "DEMO"]
Timeframe = Literal["D", "W", "M"]

PIPELINE_VERSION = "features-v1"
SCORE_VERSION = "score-v1"
PERIODS_PER_YEAR: dict[Timeframe, int] = {"D": 252, "W": 52, "M": 12}


class LabError(ValueError):
    """Errore atteso del laboratorio, sicuro da mostrare.

    `code` e un reason code stabile (es. `LAB_NO_REAL_SERIES`); `message` e un testo
    italiano senza percorsi, URL, tracce o segreti.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(code)
