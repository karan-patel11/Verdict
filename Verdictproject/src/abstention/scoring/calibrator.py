"""Kamath calibrator — a random forest predicting extractor correctness (F16).

Kamath, Jia & Liang 2020 §4.3 (verified against print): "a random forest classifier with
seven features: passage length, the length of the predicted answer ŷ, and the top five
softmax probabilities." Project analogues live in domain.models.CalibratorFeatures. The
calibrator's predicted P(correct) is the calibrated confidence fed to the Bayes-optimal
router (deferral/router.py).

Two load-bearing design facts, both cited:
- OOD-ness (ood_score) is a FEATURE in the vector, never a routing trigger (invariant 4;
  Kamath App. A.3: an outlier detector routes worse than plain MaxProb).
- The calibrator is version-locked to TAXONOMY_VERSION. Reason frequency by segment is a
  disparate-impact surface, so a calibrator fitted under one reason taxonomy must not be
  reused under another — load() refuses a version mismatch (invariant 12; tested in
  tests/test_taxonomy.py, step 5).
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..domain.models import CalibratorFeatures
from ..domain.taxonomy import TAXONOMY_VERSION


class CalibratorVersionMismatch(RuntimeError):
    """A persisted calibrator was fitted under a different TAXONOMY_VERSION. Prior
    calibration is invalidated by a taxonomy change; refuse to load it."""


class CalibratorNotFitted(RuntimeError):
    pass


@dataclass
class KamathCalibrator:
    """RandomForest over CalibratorFeatures.to_vector(). Thin wrapper so the guarantee
    machinery depends on the feature contract, not on sklearn."""

    n_estimators: int = 200
    random_state: int = 0
    taxonomy_version: str = TAXONOMY_VERSION

    def __post_init__(self) -> None:
        self._model = None  # lazily constructed at fit()

    def fit(
        self, features: Sequence[CalibratorFeatures], correct: Sequence[int]
    ) -> "KamathCalibrator":
        from sklearn.ensemble import RandomForestClassifier

        if len(features) != len(correct):
            raise ValueError("features and correct labels must align")
        if len(set(correct)) < 2:
            raise ValueError(
                "calibrator needs both correct and incorrect examples to estimate P(correct)"
            )
        X = [f.to_vector() for f in features]
        self._model = RandomForestClassifier(
            n_estimators=self.n_estimators, random_state=self.random_state
        )
        self._model.fit(X, list(correct))
        self._classes = list(self._model.classes_)
        return self

    def predict_confidence(self, features: CalibratorFeatures) -> float:
        """Calibrated P(extractor correct) ∈ [0, 1]."""
        if self._model is None:
            raise CalibratorNotFitted("call fit() before predict_confidence()")
        proba = self._model.predict_proba([features.to_vector()])[0]
        idx = self._classes.index(1) if 1 in self._classes else int(len(self._classes) - 1)
        return float(proba[idx])

    def save(self, path: str | Path) -> None:
        if self._model is None:
            raise CalibratorNotFitted("nothing to save; call fit() first")
        payload = {
            "taxonomy_version": self.taxonomy_version,
            "model": self._model,
            "classes": self._classes,
            "n_estimators": self.n_estimators,
            "random_state": self.random_state,
        }
        Path(path).write_bytes(pickle.dumps(payload))

    @classmethod
    def load(cls, path: str | Path) -> "KamathCalibrator":
        payload = pickle.loads(Path(path).read_bytes())
        persisted = payload.get("taxonomy_version")
        if persisted != TAXONOMY_VERSION:
            raise CalibratorVersionMismatch(
                f"calibrator was fitted under taxonomy {persisted!r}, but the running "
                f"taxonomy is {TAXONOMY_VERSION!r}; changing the reason taxonomy invalidates "
                "prior calibration (invariant 12)"
            )
        obj = cls(
            n_estimators=payload["n_estimators"],
            random_state=payload["random_state"],
            taxonomy_version=persisted,
        )
        obj._model = payload["model"]
        obj._classes = payload["classes"]
        return obj
