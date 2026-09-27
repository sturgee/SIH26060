
import re
from typing import Any, Dict, List, Optional
import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy import select, func

from .database import async_session
from .models import TelemetryMeasurement


class AnomalyDetector:
    def __init__(self, contamination: float = 0.05):
        self.model = IsolationForest(contamination=contamination, random_state=42)
        self.is_fitted = False
        self.feature_keys = [
            "environment.external_temperature.value",
            "environment.wind_speed.value",
            "energy.generators[0].output_power",
            "energy.generators[0].engine_temperature",
        ]

    def _extract_path_value(self, payload: Dict[str, Any], path: str) -> Optional[float]:
        """Safely extracts a numeric value from a nested dict/list path."""
        # Convert array indices like [0] to .0 for uniform splitting
        normalized_path = re.sub(r'\[(\d+)\]', r'.\1', path)
        tokens = normalized_path.split(".")
        
        curr: Any = payload
        for token in tokens:
            if isinstance(curr, dict) and token in curr:
                curr = curr[token]
            elif isinstance(curr, list) and token.isdigit():
                idx = int(token)
                if 0 <= idx < len(curr):
                    curr = curr[idx]
                else:
                    return None
            else:
                return None

        if isinstance(curr, (int, float)) and not isinstance(curr, bool):
            return float(curr)
        return None

    async def train(self, time_bucket_seconds: int = 60) -> None:
        """
        Trains Isolation Forest by grouping telemetry metrics into time buckets
        to account for asynchronous sensor reporting.
        """
        async with async_session() as session:
            # Group timestamps into buckets (e.g., 1-minute intervals)
            bucket_col = func.strftime('%Y-%m-%d %H:%M:00', TelemetryMeasurement.timestamp)

            stmt = (
                select(
                    bucket_col.label("bucket"),
                    TelemetryMeasurement.metric,
                    func.avg(TelemetryMeasurement.value).label("avg_value")
                )
                .where(TelemetryMeasurement.metric.in_(self.feature_keys))
                .group_by(bucket_col, TelemetryMeasurement.metric)
                .order_by(bucket_col.desc())
                .limit(4000)  # Fetches up to 1000 full 4-metric vectors
            )
            result = await session.execute(stmt)
            rows = result.all()

        if not rows:
            return

        # Pivot grouped records into complete feature rows
        records_by_bucket: Dict[Any, Dict[str, float]] = {}
        for bucket, metric, avg_value in rows:
            records_by_bucket.setdefault(bucket, {})[metric] = avg_value

        feature_matrix = [
            [metric_dict[k] for k in self.feature_keys]
            for metric_dict in records_by_bucket.values()
            if len(metric_dict) == len(self.feature_keys)
        ]

        if len(feature_matrix) >= 10:
            # Fit a new instance to prevent concurrent prediction read issues during fit
            new_model = IsolationForest(contamination=self.model.contamination, random_state=42)
            new_model.fit(np.array(feature_matrix))
            self.model = new_model
            self.is_fitted = True

    def detect(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Evaluates live MQTT telemetry packet for structural/cross-domain anomalies."""
        if not self.is_fitted:
            return {"status": "UNINITIALIZED", "is_anomaly": False, "score": 0.0}

        current_features = []
        for key in self.feature_keys:
            val = self._extract_path_value(payload, key)
            if val is not None:
                current_features.append(val)
            else:
                return {"status": "INCOMPLETE_DATA", "is_anomaly": False, "score": 0.0}

        sample = np.array([current_features])
        prediction = self.model.predict(sample)[0]  # 1 for normal, -1 for anomaly
        score = self.model.decision_function(sample)[0]

        is_anomaly = bool(prediction == -1)
        return {
            "status": "ANOMALY_DETECTED" if is_anomaly else "NORMAL",
            "is_anomaly": is_anomaly,
            "anomaly_score": round(float(score), 4),
            "recommendation": (
                "Inspect generator thermal differential or sudden wind load"
                if is_anomaly
                else "Nominal"
            ),
        }


detector = AnomalyDetector()