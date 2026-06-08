from __future__ import annotations

import json
import sqlite3
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.app.config import get_settings
from backend.app.models import MLTrainIn
from backend.app.services.common import now_utc as _now
from backend.app.services.ml_dataset_service import FEATURE_COLUMNS, MLDatasetService


@dataclass
class MLEngine:
    dataset_service: MLDatasetService = field(default_factory=MLDatasetService)

    def get_status(self, connection: sqlite3.Connection) -> dict[str, Any]:
        models_count = int(connection.execute("SELECT COUNT(*) AS count FROM ml_models").fetchone()["count"] or 0)
        return {
            "models_count": models_count,
            "latest_model": self._latest_model(connection),
            "latest_training_run": self._latest_training_run(connection),
            "available_targets": ["POSITIVE_RETURN", "OUTPERFORM_BENCHMARK", "DRAWDOWN_RISK"],
            "available_model_types": ["LOGISTIC_REGRESSION", "RANDOM_FOREST", "HIST_GRADIENT_BOOSTING"],
            "ml_ready": models_count > 0,
            "message": "ML pronto." if models_count > 0 else "Nessun modello ML disponibile. Addestra un modello da AI Lab.",
        }

    def train_model(self, connection: sqlite3.Connection, config: MLTrainIn) -> dict[str, Any]:
        selected_symbols, selection_warnings = self._resolve_training_symbols(connection, config)
        storage_config = config.model_copy(update={"symbols": selected_symbols})
        dataset = self.dataset_service.build_ml_dataset(
            connection=connection,
            symbols=selected_symbols,
            horizon_days=config.horizon_days,
            target_type=config.target_type,
            benchmark_symbol=config.benchmark_symbol,
        )
        if len(dataset) < config.min_samples:
            raise ValueError(
                f"Pochi dati per il training: {len(dataset)} campioni disponibili, minimo richiesto {config.min_samples}."
            )

        train, test = self.dataset_service.split_train_test_time_based(dataset, config.test_size_time_percent)
        if train.empty or test.empty:
            raise ValueError("Split train/test insufficiente per addestrare il modello.")
        if train["target"].nunique() < 2:
            raise ValueError("Target con una sola classe nel training set; servono esempi positivi e negativi.")

        x_train = train[FEATURE_COLUMNS]
        y_train = train["target"].astype(int)
        x_test = test[FEATURE_COLUMNS]
        y_test = test["target"].astype(int)
        model = self._build_model(config.model_type)
        model.fit(x_train, y_train)

        metrics = self.evaluate_model(model, x_test, y_test)
        metrics["walk_forward"] = self._walk_forward_cv(dataset, config.model_type, config.cv_folds)
        warnings = selection_warnings + self._training_warnings(metrics, len(dataset))
        explanation = self.explain_model_basic(model)
        if not explanation.get("feature_importance"):
            ranked = self._permutation_importance(model, x_test, y_test)
            explanation = {"feature_importance": ranked, "top_features_positive": ranked[:10], "top_features_negative": []}
        metrics.update(explanation)
        metrics["warnings"] = warnings
        metrics["samples_count"] = int(len(dataset))
        metrics["train_samples"] = int(len(train))
        metrics["test_samples"] = int(len(test))

        now = _now()
        training_run_id = self._insert_training_run(connection, storage_config, train, test, metrics, now)
        metrics["training_run_id"] = training_run_id
        model_id = self._insert_model(connection, storage_config, metrics, now)
        model_path = self.save_model(model, model_id, storage_config, metrics)
        connection.execute("UPDATE ml_models SET model_path = ? WHERE id = ?", (str(model_path), model_id))

        return {
            "model_id": model_id,
            "training_run": self.get_training_run(connection, training_run_id),
            "metrics": metrics,
            "features_used": FEATURE_COLUMNS,
            "warnings": warnings,
        }

    def evaluate_model(self, model: Pipeline, x_test: pd.DataFrame, y_test: pd.Series) -> dict[str, Any]:
        predictions = model.predict(x_test)
        probabilities = self._positive_probabilities(model, x_test)
        metrics: dict[str, Any] = {
            "accuracy": round(float(accuracy_score(y_test, predictions)), 6),
            "precision": round(float(precision_score(y_test, predictions, zero_division=0)), 6),
            "recall": round(float(recall_score(y_test, predictions, zero_division=0)), 6),
            "f1_score": round(float(f1_score(y_test, predictions, zero_division=0)), 6),
            "confusion_matrix": confusion_matrix(y_test, predictions, labels=[0, 1]).tolist(),
        }
        try:
            metrics["roc_auc"] = round(float(roc_auc_score(y_test, probabilities)), 6) if y_test.nunique() > 1 else None
        except ValueError:
            metrics["roc_auc"] = None
        return metrics

    def _walk_forward_cv(self, dataset: pd.DataFrame, model_type: str, folds: int) -> dict[str, Any] | None:
        """Validazione walk-forward a finestra espansiva: media metriche su piu periodi futuri."""
        fold_data = self.dataset_service.walk_forward_folds(dataset, folds)
        if not fold_data:
            return None
        accuracies: list[float] = []
        f1_values: list[float] = []
        auc_values: list[float] = []
        for train, test in fold_data:
            if train["target"].nunique() < 2 or test.empty:
                continue
            model = self._build_model(model_type)
            model.fit(train[FEATURE_COLUMNS], train["target"].astype(int))
            fold_metrics = self.evaluate_model(model, test[FEATURE_COLUMNS], test["target"].astype(int))
            accuracies.append(fold_metrics["accuracy"])
            f1_values.append(fold_metrics["f1_score"])
            if fold_metrics.get("roc_auc") is not None:
                auc_values.append(fold_metrics["roc_auc"])
        if not accuracies:
            return None
        return {
            "folds": len(accuracies),
            "accuracy_mean": round(statistics.fmean(accuracies), 6),
            "accuracy_std": round(statistics.pstdev(accuracies), 6) if len(accuracies) > 1 else 0.0,
            "f1_mean": round(statistics.fmean(f1_values), 6),
            "roc_auc_mean": round(statistics.fmean(auc_values), 6) if auc_values else None,
        }

    def save_model(self, model: Pipeline, model_id: int, config: MLTrainIn, metrics: dict[str, Any]) -> Path:
        model_dir = get_settings().database_path.parent / "ml_models"
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / f"ml_model_{model_id}.joblib"
        joblib.dump(
            {
                "model": model,
                "features": FEATURE_COLUMNS,
                "metadata": {
                    "model_id": model_id,
                    "model_name": config.model_name,
                    "model_type": config.model_type,
                    "target_type": config.target_type,
                    "horizon_days": config.horizon_days,
                    "metrics": metrics,
                },
            },
            model_path,
        )
        return model_path

    def load_model(self, connection: sqlite3.Connection, model_id: int) -> tuple[Pipeline, dict[str, Any]]:
        model_row = connection.execute("SELECT * FROM ml_models WHERE id = ?", (model_id,)).fetchone()
        if model_row is None:
            raise ValueError("Modello ML non trovato.")
        model_path = model_row["model_path"]
        if not model_path or not Path(model_path).exists():
            raise ValueError("File modello ML non disponibile. Riaddestra il modello.")
        bundle = joblib.load(model_path)
        return bundle["model"], self._model_row_to_dict(model_row)

    def predict_for_symbol(
        self,
        connection: sqlite3.Connection,
        symbol: str,
        model_id: int | None = None,
    ) -> dict[str, Any]:
        selected_model = self.get_model(connection, model_id) if model_id else self._latest_model(connection)
        if selected_model is None:
            raise ValueError("Nessun modello ML disponibile. Addestra un modello da AI Lab.")

        model, metadata = self.load_model(connection, int(selected_model["id"]))
        features = self.dataset_service.build_features_for_symbol(connection, symbol)
        if not features:
            raise ValueError(f"Feature ML non disponibili per {symbol.upper()}.")
        x_frame = pd.DataFrame([{column: features.get(column, 0.0) for column in FEATURE_COLUMNS}])
        probability = float(self._positive_probabilities(model, x_frame)[0])
        predicted_label = self._label_from_probability(metadata["target_type"], probability)
        confidence, warnings = self._confidence(probability, metadata["metrics"])
        explanation = self.explain_prediction_basic(metadata, features, probability)
        explanation["warnings"] = warnings

        probabilities = {
            "probability_positive": probability if metadata["target_type"] == "POSITIVE_RETURN" else None,
            "probability_outperform": probability if metadata["target_type"] == "OUTPERFORM_BENCHMARK" else None,
            "probability_drawdown": probability if metadata["target_type"] == "DRAWDOWN_RISK" else None,
        }
        now = _now()
        cursor = connection.execute(
            """
            INSERT INTO ml_predictions (
                model_id, symbol, prediction_date, horizon_days, target_type,
                probability_positive, probability_outperform, probability_drawdown,
                predicted_label, confidence, features_snapshot_json, explanation_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metadata["id"],
                symbol.upper(),
                now[:10],
                metadata["horizon_days"],
                metadata["target_type"],
                probabilities["probability_positive"],
                probabilities["probability_outperform"],
                probabilities["probability_drawdown"],
                predicted_label,
                confidence,
                json.dumps(features),
                json.dumps(explanation),
                now,
            ),
        )
        return {
            "id": int(cursor.lastrowid),
            "symbol": symbol.upper(),
            "model_id": metadata["id"],
            "horizon_days": metadata["horizon_days"],
            "target_type": metadata["target_type"],
            "prediction_date": now[:10],
            "probabilities": probabilities,
            **probabilities,
            "predicted_label": predicted_label,
            "confidence": confidence,
            "features_snapshot": features,
            "explanation": explanation,
            "warnings": warnings,
            "created_at": now,
        }

    def predict_all_watchlist(self, connection: sqlite3.Connection, model_id: int | None = None) -> dict[str, Any]:
        selected_model = self.get_model(connection, model_id) if model_id else self._latest_model(connection)
        if selected_model is None:
            raise ValueError("Nessun modello ML disponibile. Addestra un modello da AI Lab.")
        symbols = [
            row["symbol"]
            for row in connection.execute("SELECT symbol FROM assets ORDER BY asset_type, symbol").fetchall()
        ]
        predictions: list[dict[str, Any]] = []
        warnings: list[str] = []
        for symbol in symbols:
            try:
                predictions.append(self.predict_for_symbol(connection, symbol, int(selected_model["id"])))
            except ValueError as exc:
                warnings.append(f"{symbol}: {exc}")
        return {"model_id": int(selected_model["id"]), "predictions": predictions, "warnings": warnings}

    def _resolve_training_symbols(
        self,
        connection: sqlite3.Connection,
        config: MLTrainIn,
    ) -> tuple[list[str], list[str]]:
        warnings: list[str] = []
        symbols = [symbol.strip().upper() for symbol in config.symbols if symbol.strip()]
        if not symbols:
            symbols = [
                row["symbol"]
                for row in connection.execute(
                    """
                    SELECT DISTINCT a.symbol
                    FROM assets a
                    JOIN price_history ph ON ph.asset_id = a.id
                    ORDER BY a.symbol
                    """
                ).fetchall()
            ]
            warnings.append("Training su tutti gli asset con storico prezzi locale.")
        if len(symbols) > 120:
            warnings.append("Universo ampio: limitato a 120 asset per ridurre tempi e overfitting.")
            symbols = symbols[:120]
        deduplicated = list(dict.fromkeys(symbols))
        if not deduplicated:
            raise ValueError("Nessun asset con dati prezzo disponibile per il training ML.")
        return deduplicated, warnings

    def explain_prediction_basic(
        self,
        model_metadata: dict[str, Any],
        features: dict[str, float],
        probability: float,
    ) -> dict[str, Any]:
        metrics = model_metadata.get("metrics", {})
        positive = metrics.get("top_features_positive") or metrics.get("feature_importance", [])[:6]
        negative = metrics.get("top_features_negative", [])
        important_names = [item["feature"] for item in positive[:5] if isinstance(item, dict) and "feature" in item]
        important_names += [item["feature"] for item in negative[:5] if isinstance(item, dict) and "feature" in item]
        feature_values = {name: round(float(features.get(name, 0.0)), 6) for name in dict.fromkeys(important_names)}
        return {
            "probability": round(probability, 6),
            "top_features_positive": positive[:6],
            "top_features_negative": negative[:6],
            "feature_values": feature_values,
            "message": "ML sperimentale: usa probabilita e feature, non prevede il prezzo esatto.",
        }

    def list_models(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute("SELECT * FROM ml_models ORDER BY trained_at DESC, id DESC").fetchall()
        return [self._model_row_to_dict(row) for row in rows]

    def get_model(self, connection: sqlite3.Connection, model_id: int | None) -> dict[str, Any] | None:
        if model_id is None:
            return self._latest_model(connection)
        row = connection.execute("SELECT * FROM ml_models WHERE id = ?", (model_id,)).fetchone()
        if row is None:
            return None
        model = self._model_row_to_dict(row)
        training_id = model["metrics"].get("training_run_id") if isinstance(model.get("metrics"), dict) else None
        model["training_run"] = self.get_training_run(connection, int(training_id)) if training_id else None
        return model

    def list_training_runs(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = connection.execute("SELECT * FROM ml_training_runs ORDER BY created_at DESC, id DESC").fetchall()
        return [self._training_row_to_dict(row) for row in rows]

    def get_training_run(self, connection: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
        row = connection.execute("SELECT * FROM ml_training_runs WHERE id = ?", (run_id,)).fetchone()
        return self._training_row_to_dict(row) if row else None

    def latest_predictions(self, connection: sqlite3.Connection, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        rows = connection.execute(
            """
            SELECT *
            FROM ml_predictions
            WHERE UPPER(symbol) = UPPER(?)
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (symbol, max(1, min(limit, 50))),
        ).fetchall()
        return [self._prediction_row_to_dict(row) for row in rows]

    def _build_model(self, model_type: str) -> Pipeline:
        if model_type == "LOGISTIC_REGRESSION":
            return Pipeline(
                steps=[
                    ("imputer", SimpleImputer(strategy="median")),
                    ("scaler", StandardScaler()),
                    ("model", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
                ]
            )
        if model_type == "RANDOM_FOREST":
            return Pipeline(
                steps=[
                    ("imputer", SimpleImputer(strategy="median")),
                    (
                        "model",
                        RandomForestClassifier(
                            n_estimators=200,
                            max_depth=8,
                            min_samples_leaf=4,
                            class_weight="balanced_subsample",
                            random_state=42,
                            n_jobs=1,
                        ),
                    ),
                ]
            )
        if model_type == "HIST_GRADIENT_BOOSTING":
            return Pipeline(
                steps=[
                    (
                        "model",
                        HistGradientBoostingClassifier(
                            max_iter=300,
                            max_depth=4,
                            learning_rate=0.06,
                            l2_regularization=1.0,
                            class_weight="balanced",
                            random_state=42,
                        ),
                    ),
                ]
            )
        raise ValueError("Tipo modello ML non supportato.")

    def _positive_probabilities(self, model: Pipeline, x_frame: pd.DataFrame) -> np.ndarray:
        probabilities = model.predict_proba(x_frame)
        classifier = model.named_steps["model"]
        classes = list(classifier.classes_)
        positive_index = classes.index(1) if 1 in classes else len(classes) - 1
        return probabilities[:, positive_index]

    def explain_model_basic(self, model: Pipeline) -> dict[str, Any]:
        classifier = model.named_steps["model"]
        if hasattr(classifier, "coef_"):
            coefficients = classifier.coef_[0]
            positive = [
                {"feature": feature, "importance": round(float(coef), 6)}
                for feature, coef in sorted(
                    zip(FEATURE_COLUMNS, coefficients, strict=False), key=lambda item: item[1], reverse=True
                )
                if coef > 0
            ]
            negative = [
                {"feature": feature, "importance": round(float(coef), 6)}
                for feature, coef in sorted(zip(FEATURE_COLUMNS, coefficients, strict=False), key=lambda item: item[1])
                if coef < 0
            ]
            return {
                "feature_importance": sorted(
                    [
                        {"feature": feature, "importance": round(float(abs(coef)), 6)}
                        for feature, coef in zip(FEATURE_COLUMNS, coefficients, strict=False)
                    ],
                    key=lambda item: item["importance"],
                    reverse=True,
                ),
                "top_features_positive": positive[:10],
                "top_features_negative": negative[:10],
            }
        importances = getattr(classifier, "feature_importances_", None)
        if importances is None:
            return {"feature_importance": [], "top_features_positive": [], "top_features_negative": []}
        ranked = sorted(
            [
                {"feature": feature, "importance": round(float(value), 6)}
                for feature, value in zip(FEATURE_COLUMNS, importances, strict=False)
            ],
            key=lambda item: item["importance"],
            reverse=True,
        )
        return {"feature_importance": ranked, "top_features_positive": ranked[:10], "top_features_negative": []}

    def _permutation_importance(
        self,
        model: Pipeline,
        x_test: pd.DataFrame,
        y_test: pd.Series,
    ) -> list[dict[str, Any]]:
        """Importanza per permutazione: funziona con qualsiasi modello (es. gradient boosting)."""
        if len(x_test) < 10 or y_test.nunique() < 2:
            return []
        try:
            scoring = "roc_auc" if y_test.nunique() == 2 else "accuracy"
            result = permutation_importance(
                model, x_test, y_test, n_repeats=5, random_state=42, scoring=scoring, n_jobs=1
            )
        except Exception:
            return []
        return sorted(
            [
                {"feature": feature, "importance": round(float(value), 6)}
                for feature, value in zip(FEATURE_COLUMNS, result.importances_mean, strict=False)
            ],
            key=lambda item: item["importance"],
            reverse=True,
        )

    def _confidence(self, probability: float, metrics: dict[str, Any]) -> tuple[str, list[str]]:
        warnings: list[str] = []
        strength = max(probability, 1 - probability)
        f1_value = float(metrics.get("f1_score") or 0.0)
        roc_auc = metrics.get("roc_auc")
        if f1_value < 0.45:
            warnings.append("Metriche modello deboli: usa il risultato con prudenza.")
        if roc_auc is not None and float(roc_auc) < 0.52:
            warnings.append("ROC AUC vicino al caso casuale.")
        if strength >= 0.70 and f1_value >= 0.55 and (roc_auc is None or float(roc_auc) >= 0.55):
            return "HIGH", warnings
        if strength >= 0.58 and f1_value >= 0.45:
            return "MEDIUM", warnings
        warnings.append("Probabilita vicina a 0.50: segnale ML poco deciso.")
        return "LOW", warnings

    def _label_from_probability(self, target_type: str, probability: float) -> str:
        positive = probability >= 0.5
        if target_type == "POSITIVE_RETURN":
            return "POSITIVE_RETURN" if positive else "NON_POSITIVE_RETURN"
        if target_type == "OUTPERFORM_BENCHMARK":
            return "OUTPERFORM" if positive else "UNDERPERFORM"
        if target_type == "DRAWDOWN_RISK":
            return "DRAWDOWN_RISK" if positive else "LOW_DRAWDOWN_RISK"
        return "POSITIVE" if positive else "NEGATIVE"

    def _training_warnings(self, metrics: dict[str, Any], samples_count: int) -> list[str]:
        warnings: list[str] = []
        if samples_count < 500:
            warnings.append("Campione limitato: rischio overfitting elevato.")
        if float(metrics.get("f1_score") or 0.0) < 0.45:
            warnings.append("F1 basso: modello debole o target rumoroso.")
        if metrics.get("roc_auc") is not None and float(metrics["roc_auc"]) < 0.52:
            warnings.append("ROC AUC vicino al caso casuale.")
        walk_forward = metrics.get("walk_forward")
        if (
            isinstance(walk_forward, dict)
            and walk_forward.get("roc_auc_mean") is not None
            and float(walk_forward["roc_auc_mean"]) < 0.52
        ):
            warnings.append("Walk-forward debole: il modello non generalizza tra periodi diversi.")
        return warnings

    def _insert_training_run(
        self,
        connection: sqlite3.Connection,
        config: MLTrainIn,
        train: pd.DataFrame,
        test: pd.DataFrame,
        metrics: dict[str, Any],
        now: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO ml_training_runs (
                model_name, target_type, horizon_days, train_start_date, train_end_date,
                test_start_date, test_end_date, samples_count, accuracy, precision,
                recall, f1_score, roc_auc, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                config.model_name,
                config.target_type,
                config.horizon_days,
                str(train["date"].min()),
                str(train["date"].max()),
                str(test["date"].min()),
                str(test["date"].max()),
                int(metrics["samples_count"]),
                metrics.get("accuracy"),
                metrics.get("precision"),
                metrics.get("recall"),
                metrics.get("f1_score"),
                metrics.get("roc_auc"),
                now,
            ),
        )
        return int(cursor.lastrowid)

    def _insert_model(
        self,
        connection: sqlite3.Connection,
        config: MLTrainIn,
        metrics: dict[str, Any],
        now: str,
    ) -> int:
        cursor = connection.execute(
            """
            INSERT INTO ml_models (
                model_name, model_type, target_type, horizon_days, symbols_scope,
                features_json, metrics_json, model_path, trained_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                config.model_name,
                config.model_type,
                config.target_type,
                config.horizon_days,
                json.dumps([symbol.upper() for symbol in config.symbols]),
                json.dumps(FEATURE_COLUMNS),
                json.dumps(metrics),
                "",
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)

    def _latest_model(self, connection: sqlite3.Connection) -> dict[str, Any] | None:
        row = connection.execute("SELECT * FROM ml_models ORDER BY trained_at DESC, id DESC LIMIT 1").fetchone()
        return self._model_row_to_dict(row) if row else None

    def _latest_training_run(self, connection: sqlite3.Connection) -> dict[str, Any] | None:
        row = connection.execute("SELECT * FROM ml_training_runs ORDER BY created_at DESC, id DESC LIMIT 1").fetchone()
        return self._training_row_to_dict(row) if row else None

    def _model_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "model_name": row["model_name"],
            "model_type": row["model_type"],
            "target_type": row["target_type"],
            "horizon_days": int(row["horizon_days"]),
            "symbols_scope": self._json_value(row["symbols_scope"], []),
            "features": self._json_value(row["features_json"], []),
            "metrics": self._json_value(row["metrics_json"], {}),
            "model_path": row["model_path"],
            "trained_at": row["trained_at"],
            "created_at": row["created_at"],
        }

    def _training_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "model_name": row["model_name"],
            "target_type": row["target_type"],
            "horizon_days": int(row["horizon_days"]),
            "train_start_date": row["train_start_date"],
            "train_end_date": row["train_end_date"],
            "test_start_date": row["test_start_date"],
            "test_end_date": row["test_end_date"],
            "samples_count": int(row["samples_count"] or 0),
            "accuracy": row["accuracy"],
            "precision": row["precision"],
            "recall": row["recall"],
            "f1_score": row["f1_score"],
            "roc_auc": row["roc_auc"],
            "created_at": row["created_at"],
        }

    def _prediction_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        probabilities = {
            "probability_positive": row["probability_positive"],
            "probability_outperform": row["probability_outperform"],
            "probability_drawdown": row["probability_drawdown"],
        }
        explanation = self._json_value(row["explanation_json"], {})
        return {
            "id": int(row["id"]),
            "symbol": row["symbol"],
            "model_id": int(row["model_id"]) if row["model_id"] is not None else 0,
            "horizon_days": int(row["horizon_days"]),
            "target_type": row["target_type"],
            "prediction_date": row["prediction_date"],
            "probabilities": probabilities,
            **probabilities,
            "predicted_label": row["predicted_label"],
            "confidence": row["confidence"] or "LOW",
            "features_snapshot": self._json_value(row["features_snapshot_json"], {}),
            "explanation": explanation,
            "warnings": explanation.get("warnings", []) if isinstance(explanation, dict) else [],
            "created_at": row["created_at"],
        }

    def _json_value(self, value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
