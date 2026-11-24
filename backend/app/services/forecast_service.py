"""
Phase 9: Real AI Demand Forecasting Engine (Python ML — scikit-learn + pure-NumPy/Python fallback).
Strict Scientific & Zero-Fabrication Guarantees:
- Trained ONLY on verified confirmed historical orders (Order.payment_status == 'CONFIRMED').
- Enforces minimum historical data threshold (>= 7 distinct sales days); if insufficient,
  returns explicit 'Insufficient historical data to generate a reliable forecast.' (NEVER fakes).
- Uses strict chronological 80/20 train/validation split (zero future leakage!).
- Evaluates real Baseline vs Ridge Regression vs Decision Tree Ensemble (RandomForest) vs
  Gradient Boosted Trees on MAE, RMSE, and MAPE.
- Lazy-loads scikit-learn so FastAPI cold starts remain instant, and automatically falls back
  to exact pure-Python/NumPy Ridge & Boosted/Bagged CART Regression Trees if Windows Application
  Control blocks native SciPy Fortran DLLs.
- Labels all outputs explicitly as data_classification='ai_predicted' with uncertainty bounds.
"""

import math
import random
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time_utils import get_college_tz, today_college
from app.models.college import Canteen, CollegeHoliday
from app.models.enterprise import DemandForecast, ForecastEvaluation, ForecastModel
from app.models.event import CollegeEvent
from app.models.inventory import InventoryItem
from app.models.menu import FoodCategory, FoodItem, Ingredient, Recipe, RecipeIngredient
from app.models.order import Order, OrderItem
from app.services.audit_service import record_audit_log
from app.services.inventory_service import get_unexpired_stock_quantity

MIN_HISTORICAL_DAYS = 7
FEATURE_COLUMNS = [
    "item_code",
    "day_of_week",
    "is_weekend",
    "day_of_month",
    "is_holiday",
    "is_event",
    "lag_1",
    "lag_7",
    "rolling_7_mean",
    "rolling_14_mean",
]


# =============================================================================
# REAL ML MODELS (SCIKIT-LEARN PREFERRED + EXACT PURE-PYTHON CART/RIDGE FALLBACK)
# =============================================================================


class _PureRidgeRegressor:
    """Exact L2-regularized linear regression solved via Gaussian elimination on (X^T X + alpha I) w = X^T y."""

    def __init__(self, alpha: float = 1.0) -> None:
        self.alpha = float(alpha)
        self.weights: list[float] = []
        self.bias: float = 0.0
        self.means: list[float] = []
        self.stds: list[float] = []

    def fit(self, X: list[list[float]], y: list[float]) -> "_PureRidgeRegressor":
        n = len(X)
        d = len(X[0]) if n > 0 else 0
        if n == 0 or d == 0:
            self.weights = [0.0] * d
            self.bias = 0.0
            return self
        self.bias = sum(y) / n
        self.means = [sum(row[j] for row in X) / n for j in range(d)]
        self.stds = []
        for j in range(d):
            var = sum((row[j] - self.means[j]) ** 2 for row in X) / n
            s = math.sqrt(var)
            self.stds.append(s if s > 1e-9 else 1.0)

        Xs = [[(row[j] - self.means[j]) / self.stds[j] for j in range(d)] for row in X]
        yc = [v - self.bias for v in y]

        # Build normal matrix A = X^T X + alpha * I and b = X^T y
        A = [[0.0] * d for _ in range(d)]
        b = [0.0] * d
        for i in range(n):
            xi = Xs[i]
            yi = yc[i]
            for j in range(d):
                b[j] += xi[j] * yi
                for k in range(j, d):
                    A[j][k] += xi[j] * xi[k]
        for j in range(d):
            A[j][j] += self.alpha
            for k in range(j + 1, d):
                A[k][j] = A[j][k]

        # Gaussian elimination with partial pivoting
        M = [A[j][:] + [b[j]] for j in range(d)]
        for col in range(d):
            piv = max(range(col, d), key=lambda r: abs(M[r][col]))
            M[col], M[piv] = M[piv], M[col]
            denom = M[col][col]
            if abs(denom) < 1e-12:
                continue
            for r in range(col + 1, d):
                factor = M[r][col] / denom
                for c in range(col, d + 1):
                    M[r][c] -= factor * M[col][c]
        w = [0.0] * d
        for r in range(d - 1, -1, -1):
            denom = M[r][r]
            if abs(denom) < 1e-12:
                w[r] = 0.0
            else:
                w[r] = (M[r][d] - sum(M[r][c] * w[c] for c in range(r + 1, d))) / denom
        self.weights = w
        return self

    def predict(self, X: list[list[float]]) -> list[float]:
        out: list[float] = []
        for row in X:
            val = self.bias
            for j, wj in enumerate(self.weights):
                val += wj * ((row[j] - self.means[j]) / self.stds[j])
            out.append(val)
        return out


class _RegressionTreeNode:
    __slots__ = ("feature", "threshold", "left", "right", "value")

    def __init__(
        self,
        *,
        value: float = 0.0,
        feature: Optional[int] = None,
        threshold: Optional[float] = None,
        left: Optional["_RegressionTreeNode"] = None,
        right: Optional["_RegressionTreeNode"] = None,
    ) -> None:
        self.value = value
        self.feature = feature
        self.threshold = threshold
        self.left = left
        self.right = right


class _PureCARTRegressor:
    """Real variance-reduction CART regression tree."""

    def __init__(self, max_depth: int = 4, min_samples_leaf: int = 2) -> None:
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.root: Optional[_RegressionTreeNode] = None

    def _build(self, X: list[list[float]], y: list[float], depth: int, feat_indices: list[int]) -> _RegressionTreeNode:
        n = len(y)
        mean_y = sum(y) / n if n else 0.0
        if depth >= self.max_depth or n < self.min_samples_leaf * 2:
            return _RegressionTreeNode(value=mean_y)

        total_var = sum((v - mean_y) ** 2 for v in y)
        if total_var < 1e-9:
            return _RegressionTreeNode(value=mean_y)

        best_gain = 0.0
        best_feat = None
        best_thr = None
        for f in feat_indices:
            vals = sorted({row[f] for row in X})
            if len(vals) <= 1:
                continue
            # Sample up to 12 candidate thresholds cleanly
            step = max(1, len(vals) // 12)
            cands = [(vals[i] + vals[i + 1]) / 2.0 for i in range(0, len(vals) - 1, step)]
            for thr in cands:
                ly = [y[i] for i in range(n) if X[i][f] <= thr]
                ry = [y[i] for i in range(n) if X[i][f] > thr]
                if len(ly) < self.min_samples_leaf or len(ry) < self.min_samples_leaf:
                    continue
                lm = sum(ly) / len(ly)
                rm = sum(ry) / len(ry)
                sse = sum((v - lm) ** 2 for v in ly) + sum((v - rm) ** 2 for v in ry)
                gain = total_var - sse
                if gain > best_gain:
                    best_gain = gain
                    best_feat = f
                    best_thr = thr

        if best_feat is None or best_thr is None:
            return _RegressionTreeNode(value=mean_y)

        lX, ly_v, rX, ry_v = [], [], [], []
        for i in range(n):
            if X[i][best_feat] <= best_thr:
                lX.append(X[i])
                ly_v.append(y[i])
            else:
                rX.append(X[i])
                ry_v.append(y[i])
        return _RegressionTreeNode(
            value=mean_y,
            feature=best_feat,
            threshold=best_thr,
            left=self._build(lX, ly_v, depth + 1, feat_indices),
            right=self._build(rX, ry_v, depth + 1, feat_indices),
        )

    def fit(self, X: list[list[float]], y: list[float], feat_indices: Optional[list[int]] = None) -> "_PureCARTRegressor":
        d = len(X[0]) if X else 0
        f_idx = feat_indices if feat_indices is not None else list(range(d))
        self.root = self._build(X, y, 0, f_idx)
        return self

    def _pred_one(self, row: list[float]) -> float:
        node = self.root
        while node is not None and node.feature is not None and node.threshold is not None:
            node = node.left if row[node.feature] <= node.threshold else node.right
        return node.value if node is not None else 0.0

    def predict(self, X: list[list[float]]) -> list[float]:
        return [self._pred_one(r) for r in X]


class _PureRandomForestRegressor:
    """Real bootstrap-aggregated (Bagged) CART ensemble regressor."""

    def __init__(self, n_estimators: int = 20, max_depth: int = 5, seed: int = 42) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.seed = seed
        self.trees: list[_PureCARTRegressor] = []

    def fit(self, X: list[list[float]], y: list[float]) -> "_PureRandomForestRegressor":
        rng = random.Random(self.seed)
        n = len(X)
        d = len(X[0]) if n else 0
        self.trees = []
        if n == 0 or d == 0:
            return self
        k_feats = max(2, int(math.sqrt(d)) + 1)
        for _ in range(self.n_estimators):
            idxs = [rng.randrange(n) for _ in range(n)]
            bX = [X[i] for i in idxs]
            by = [y[i] for i in idxs]
            f_sub = rng.sample(range(d), min(d, k_feats))
            self.trees.append(_PureCARTRegressor(max_depth=self.max_depth).fit(bX, by, feat_indices=f_sub))
        return self

    def predict(self, X: list[list[float]]) -> list[float]:
        if not self.trees:
            return [0.0] * len(X)
        preds = [t.predict(X) for t in self.trees]
        m = len(self.trees)
        return [sum(preds[t][i] for t in range(m)) / m for i in range(len(X))]


class _PureGradientBoostingRegressor:
    """Real sequential residual-boosting CART regressor."""

    def __init__(self, n_estimators: int = 25, max_depth: int = 3, learning_rate: float = 0.1) -> None:
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.learning_rate = learning_rate
        self.init_pred: float = 0.0
        self.trees: list[_PureCARTRegressor] = []

    def fit(self, X: list[list[float]], y: list[float]) -> "_PureGradientBoostingRegressor":
        n = len(y)
        self.trees = []
        if n == 0:
            self.init_pred = 0.0
            return self
        self.init_pred = sum(y) / n
        preds = [self.init_pred] * n
        for _ in range(self.n_estimators):
            residuals = [y[i] - preds[i] for i in range(n)]
            tree = _PureCARTRegressor(max_depth=self.max_depth).fit(X, residuals)
            step = tree.predict(X)
            for i in range(n):
                preds[i] += self.learning_rate * step[i]
            self.trees.append(tree)
        return self

    def predict(self, X: list[list[float]]) -> list[float]:
        out = [self.init_pred] * len(X)
        for tree in self.trees:
            step = tree.predict(X)
            for i in range(len(X)):
                out[i] += self.learning_rate * step[i]
        return out


def _build_ml_candidates() -> tuple[str, dict[str, Any]]:
    """Prefer scikit-learn when available; fall back cleanly to pure-Python ML if OS blocks SciPy DLLs."""
    try:
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
        from sklearn.linear_model import Ridge

        return (
            "scikit-learn",
            {
                "ridge_regression": lambda: Ridge(alpha=1.0),
                "random_forest": lambda: RandomForestRegressor(n_estimators=60, max_depth=6, random_state=42),
                "gradient_boosting": lambda: GradientBoostingRegressor(
                    n_estimators=60, max_depth=3, learning_rate=0.08, random_state=42
                ),
            },
        )
    except Exception:
        return (
            "python_ml_native",
            {
                "ridge_regression": lambda: _PureRidgeRegressor(alpha=1.0),
                "random_forest": lambda: _PureRandomForestRegressor(n_estimators=20, max_depth=5, seed=42),
                "gradient_boosting": lambda: _PureGradientBoostingRegressor(
                    n_estimators=25, max_depth=3, learning_rate=0.1
                ),
            },
        )


def _compute_metrics(y_true: list[float], y_pred: list[float]) -> tuple[float, float, Optional[float], float]:
    n = max(1, len(y_true))
    abs_errs = [abs(t - p) for t, p in zip(y_true, y_pred)]
    sq_errs = [(t - p) ** 2 for t, p in zip(y_true, y_pred)]
    resids = [t - p for t, p in zip(y_true, y_pred)]
    mae = round(sum(abs_errs) / n, 4)
    rmse = round(math.sqrt(sum(sq_errs) / n), 4)
    pos_pcts = [abs((t - p) / t) * 100.0 for t, p in zip(y_true, y_pred) if t > 0]
    mape = round(sum(pos_pcts) / len(pos_pcts), 2) if pos_pcts else None
    mean_r = sum(resids) / n
    resid_std = math.sqrt(sum((r - mean_r) ** 2 for r in resids) / n)
    return mae, rmse, mape, resid_std


def _load_historical_sales_panel(
    db: Session,
    canteen_id: UUID,
    *,
    training_window_days: int,
) -> tuple[list[dict[str, Any]], dict[UUID, FoodItem], set[date], set[date], int]:
    tz = get_college_tz()
    local_today = today_college()
    start_d = local_today - timedelta(days=max(7, training_window_days))
    s_dt = datetime.combine(start_d, time.min, tzinfo=tz)
    e_dt = datetime.combine(local_today, time.max, tzinfo=tz)

    rows = db.execute(
        select(Order.created_at, OrderItem.food_item_id, OrderItem.quantity)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .where(
            Order.canteen_id == canteen_id,
            Order.payment_status == "CONFIRMED",
            Order.created_at >= s_dt,
            Order.created_at <= e_dt,
            OrderItem.food_item_id.is_not(None),
        )
    ).all()

    foods = {
        f.id: f
        for f in db.scalars(
            select(FoodItem).where(FoodItem.canteen_id == canteen_id, FoodItem.is_active.is_(True))
        ).all()
    }
    if not rows or not foods:
        return [], foods, set(), set(), 0

    daily_qty: dict[tuple[UUID, date], float] = {}
    distinct_sales_dates: set[date] = set()
    for created_at, fid, qty in rows:
        if fid not in foods:
            continue
        dt_utc = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at
        d_local = dt_utc.astimezone(tz).date()
        distinct_sales_dates.add(d_local)
        daily_qty[(fid, d_local)] = daily_qty.get((fid, d_local), 0.0) + float(qty or 0)

    n_sales_days = len(distinct_sales_dates)
    if n_sales_days < MIN_HISTORICAL_DAYS:
        return [], foods, set(), set(), n_sales_days

    min_d = min(distinct_sales_dates)
    max_d = max(distinct_sales_dates)
    all_dates = [min_d + timedelta(days=i) for i in range((max_d - min_d).days + 1)]

    future_end = local_today + timedelta(days=21)
    holidays = set(
        db.scalars(
            select(CollegeHoliday.holiday_date).where(
                CollegeHoliday.is_active.is_(True),
                CollegeHoliday.holiday_date >= min_d,
                CollegeHoliday.holiday_date <= future_end,
                (CollegeHoliday.canteen_id == canteen_id) | (CollegeHoliday.canteen_id.is_(None)),
            )
        ).all()
    )
    events = set(
        db.scalars(
            select(CollegeEvent.event_date).where(
                CollegeEvent.canteen_id == canteen_id,
                CollegeEvent.is_active.is_(True),
                CollegeEvent.event_date >= min_d,
                CollegeEvent.event_date <= future_end,
            )
        ).all()
    )

    active_item_ids = sorted({fid for fid, _ in daily_qty.keys()}, key=lambda u: str(u))
    item_code_map = {fid: idx for idx, fid in enumerate(active_item_ids)}
    # Skip canteen-wide zero-sales holiday closure days from training targets so holidays don't distort weekday baselines
    operating_dates = [d for d in all_dates if not (d in holidays and d not in distinct_sales_dates)]
    if len(operating_dates) < MIN_HISTORICAL_DAYS:
        operating_dates = all_dates

    # Compute per-item upper IQR outlier cap (Q3 + 3.0 * IQR) when >= 8 positive sales days exist
    item_upper_cap: dict[UUID, float] = {}
    for fid in active_item_ids:
        pos_vals = sorted(v for (f_id, _d), v in daily_qty.items() if f_id == fid and v > 0)
        if len(pos_vals) >= 8:
            q1 = pos_vals[len(pos_vals) // 4]
            q3 = pos_vals[(3 * len(pos_vals)) // 4]
            iqr = max(1.0, q3 - q1)
            item_upper_cap[fid] = q3 + (3.0 * iqr)

    records: list[dict[str, Any]] = []
    for fid in active_item_ids:
        hist_vals: list[float] = []
        cap = item_upper_cap.get(fid)
        for d in operating_dates:
            raw_y = daily_qty.get((fid, d), 0.0)
            y_val = min(raw_y, cap) if (cap is not None and raw_y > cap) else raw_y
            lag_1 = hist_vals[-1] if len(hist_vals) >= 1 else 0.0
            lag_7 = hist_vals[-7] if len(hist_vals) >= 7 else (sum(hist_vals) / len(hist_vals) if hist_vals else 0.0)
            r7 = (sum(hist_vals[-7:]) / len(hist_vals[-7:])) if hist_vals else 0.0
            r14 = (sum(hist_vals[-14:]) / len(hist_vals[-14:])) if hist_vals else 0.0
            records.append(
                {
                    "food_item_id": fid,
                    "item_code": float(item_code_map[fid]),
                    "sales_date": d,
                    "day_of_week": float(d.weekday()),
                    "is_weekend": 1.0 if d.weekday() >= 5 else 0.0,
                    "day_of_month": float(d.day),
                    "is_holiday": 1.0 if d in holidays else 0.0,
                    "is_event": 1.0 if d in events else 0.0,
                    "lag_1": lag_1,
                    "lag_7": lag_7,
                    "rolling_7_mean": r7,
                    "rolling_14_mean": r14,
                    "target_qty": y_val,
                }
            )
            hist_vals.append(y_val)

    return records, foods, holidays, events, n_sales_days


def train_and_generate_forecasts(
    db: Session,
    *,
    canteen_id: UUID,
    training_window_days: int = 60,
    horizon_days: int = 7,
    force_retrain: bool = False,
    actor_user_id: Optional[UUID] = None,
) -> dict[str, Any]:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")

    records, foods, holidays, events, n_sales_days = _load_historical_sales_panel(
        db, canteen_id, training_window_days=training_window_days
    )
    if n_sales_days < MIN_HISTORICAL_DAYS or not records:
        return {
            "canteen_id": str(canteen_id),
            "status": "insufficient_data",
            "data_classification": "unavailable",
            "historical_days_available": n_sales_days,
            "minimum_required_days": MIN_HISTORICAL_DAYS,
            "message": "Insufficient historical data to generate a reliable forecast.",
            "retrained": False,
        }

    latest_active = db.scalar(
        select(ForecastModel)
        .where(ForecastModel.canteen_id == canteen_id, ForecastModel.is_active.is_(True))
        .order_by(ForecastModel.trained_at.desc())
        .limit(1)
    )
    now = datetime.now(timezone.utc)
    if latest_active and not force_retrain:
        t_at = latest_active.trained_at
        if t_at and t_at.tzinfo is None:
            t_at = t_at.replace(tzinfo=timezone.utc)
        existing_max_horizon = (
            db.scalar(
                select(DemandForecast.horizon_days)
                .where(DemandForecast.model_id == latest_active.id)
                .order_by(DemandForecast.horizon_days.desc())
                .limit(1)
            )
            or 0
        )
        if (
            t_at
            and (now - t_at) < timedelta(hours=12)
            and latest_active.historical_days_used >= n_sales_days
            and int(existing_max_horizon) >= int(horizon_days)
        ):
            summary = get_canteen_forecast_summary(db, canteen_id, horizon_days=horizon_days)
            summary["retrained"] = False
            summary["retrain_skipped_reason"] = (
                "Active model trained within last 12 hours on identical historical window and horizon; pass force_retrain=true to override."
            )
            return summary

    # Strict chronological split (ZERO data leakage)
    unique_dates = sorted({r["sales_date"] for r in records})
    split_idx = max(4, int(len(unique_dates) * 0.8))
    if split_idx >= len(unique_dates):
        split_idx = len(unique_dates) - 1
    train_dates = set(unique_dates[:split_idx])
    val_dates = set(unique_dates[split_idx:])

    train_rows = [r for r in records if r["sales_date"] in train_dates]
    val_rows = [r for r in records if r["sales_date"] in val_dates]

    X_train = [[float(r[c]) for c in FEATURE_COLUMNS] for r in train_rows]
    y_train = [float(r["target_qty"]) for r in train_rows]
    X_val = [[float(r[c]) for c in FEATURE_COLUMNS] for r in val_rows]
    y_val = [float(r["target_qty"]) for r in val_rows]

    # 1. Baseline: causal 7-day rolling mean
    base_pred = [max(0.0, float(r["rolling_7_mean"])) for r in val_rows]
    base_mae, base_rmse, base_mape, base_std = _compute_metrics(y_val, base_pred)

    backend_engine, candidate_factories = _build_ml_candidates()
    comparison: dict[str, dict[str, Any]] = {
        "rolling_7d_baseline": {"mae": base_mae, "rmse": base_rmse, "mape": base_mape, "engine": "baseline"}
    }

    best_name = "rolling_7d_baseline"
    best_mae = base_mae
    best_rmse = base_rmse
    best_mape = base_mape
    best_std = base_std

    for name, factory in candidate_factories.items():
        est = factory()
        est.fit(X_train, y_train)
        raw_preds = est.predict(X_val)
        preds = [max(0.0, float(p)) for p in raw_preds]
        m_mae, m_rmse, m_mape, m_std = _compute_metrics(y_val, preds)
        comparison[name] = {"mae": m_mae, "rmse": m_rmse, "mape": m_mape, "engine": backend_engine}
        if m_mae <= best_mae:
            best_name = name
            best_mae = m_mae
            best_rmse = m_rmse
            best_mape = m_mape
            best_std = m_std

    # Refit selected model on full verified historical data
    X_full = [[float(r[c]) for c in FEATURE_COLUMNS] for r in records]
    y_full = [float(r["target_qty"]) for r in records]
    final_model = None
    if best_name in candidate_factories:
        final_model = candidate_factories[best_name]()
        final_model.fit(X_full, y_full)

    for old_m in db.scalars(
        select(ForecastModel).where(ForecastModel.canteen_id == canteen_id, ForecastModel.is_active.is_(True))
    ).all():
        old_m.is_active = False

    version_str = f"FC-{canteen.code}-{now.strftime('%Y%m%d%H%M%S')}"
    fm = ForecastModel(
        model_version=version_str,
        canteen_id=canteen_id,
        algorithm=best_name,
        training_window_days=training_window_days,
        historical_days_used=n_sales_days,
        sample_rows=len(records),
        mae=Decimal(str(best_mae)),
        rmse=Decimal(str(best_rmse)),
        mape=Decimal(str(best_mape)) if best_mape is not None else None,
        baseline_mae=Decimal(str(base_mae)),
        baseline_rmse=Decimal(str(base_rmse)),
        comparison_metrics_json=comparison,
        feature_columns=FEATURE_COLUMNS,
        is_active=True,
        trained_by_user_id=actor_user_id,
        trained_at=now,
    )
    db.add(fm)
    db.flush()

    distinct_items = {r["food_item_id"] for r in records}
    db.add(
        ForecastEvaluation(
            model_id=fm.id,
            canteen_id=canteen_id,
            evaluation_date=today_college(),
            mae=fm.mae,
            rmse=fm.rmse,
            mape=fm.mape,
            evaluated_items_count=len(distinct_items),
            notes=f"Chronological holdout split ({len(train_dates)} train / {len(val_dates)} val days). Engine={backend_engine}. Winner={best_name}.",
        )
    )

    # Recursive multi-step forecast per item
    by_item: dict[UUID, list[dict[str, Any]]] = {}
    for r in records:
        by_item.setdefault(r["food_item_id"], []).append(r)

    local_today = today_college()
    band_half_width = max(0.5, 1.28 * max(best_std, best_mae))
    for fid, grp in by_item.items():
        grp_sorted = sorted(grp, key=lambda x: x["sales_date"])
        item_code = float(grp_sorted[0]["item_code"])
        history_series = [float(x["target_qty"]) for x in grp_sorted]
        food_obj = foods.get(fid)
        for step in range(1, horizon_days + 1):
            f_date = local_today + timedelta(days=step)
            lag_1 = history_series[-1] if len(history_series) >= 1 else 0.0
            lag_7 = history_series[-7] if len(history_series) >= 7 else (sum(history_series) / len(history_series))
            r7 = sum(history_series[-7:]) / len(history_series[-7:])
            r14 = sum(history_series[-14:]) / len(history_series[-14:])
            feat_vec = [[
                item_code,
                float(f_date.weekday()),
                1.0 if f_date.weekday() >= 5 else 0.0,
                float(f_date.day),
                1.0 if f_date in holidays else 0.0,
                1.0 if f_date in events else 0.0,
                lag_1,
                lag_7,
                r7,
                r14,
            ]]
            pred = float(final_model.predict(feat_vec)[0]) if final_model is not None else r7
            pred = round(max(0.0, pred), 2)
            low = round(max(0.0, pred - band_half_width), 2)
            high = round(pred + band_half_width, 2)
            db.add(
                DemandForecast(
                    model_id=fm.id,
                    canteen_id=canteen_id,
                    food_item_id=fid,
                    category_id=food_obj.category_id if food_obj else None,
                    forecast_date=f_date,
                    horizon_days=step,
                    predicted_quantity=Decimal(str(pred)),
                    lower_bound=Decimal(str(low)),
                    upper_bound=Decimal(str(high)),
                    historical_days_used=n_sales_days,
                    data_classification="ai_predicted",
                    generated_at=now,
                )
            )
            history_series.append(pred)

    record_audit_log(
        db,
        action="forecasting.model_trained",
        entity_type="forecast_model",
        entity_id=version_str,
        actor_user_id=actor_user_id,
        details={"algorithm": best_name, "engine": backend_engine, "mae": best_mae, "rmse": best_rmse, "days_used": n_sales_days},
    )
    db.commit()

    summary = get_canteen_forecast_summary(db, canteen_id, horizon_days=horizon_days)
    summary["retrained"] = True
    return summary


def list_forecast_models(db: Session, canteen_id: UUID) -> list[dict]:
    rows = db.scalars(
        select(ForecastModel)
        .where(ForecastModel.canteen_id == canteen_id)
        .order_by(ForecastModel.trained_at.desc())
        .limit(25)
    ).all()
    return [
        {
            "id": str(m.id),
            "model_version": m.model_version,
            "algorithm": m.algorithm,
            "training_window_days": m.training_window_days,
            "historical_days_used": m.historical_days_used,
            "sample_rows": m.sample_rows,
            "mae": float(m.mae) if m.mae is not None else None,
            "rmse": float(m.rmse) if m.rmse is not None else None,
            "mape": float(m.mape) if m.mape is not None else None,
            "baseline_mae": float(m.baseline_mae) if m.baseline_mae is not None else None,
            "baseline_rmse": float(m.baseline_rmse) if m.baseline_rmse is not None else None,
            "comparison_metrics": m.comparison_metrics_json or {},
            "is_active": m.is_active,
            "trained_at": m.trained_at.isoformat() if m.trained_at else None,
        }
        for m in rows
    ]


def get_canteen_forecast_summary(db: Session, canteen_id: UUID, *, horizon_days: int = 7) -> dict[str, Any]:
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")

    active_model = db.scalar(
        select(ForecastModel)
        .where(ForecastModel.canteen_id == canteen_id, ForecastModel.is_active.is_(True))
        .order_by(ForecastModel.trained_at.desc())
        .limit(1)
    )
    if not active_model:
        return {
            "canteen_id": str(canteen_id),
            "canteen_name": canteen.name,
            "status": "insufficient_data",
            "data_classification": "unavailable",
            "message": "Insufficient historical data to generate a reliable forecast.",
            "active_model": None,
            "next_day_forecasts": [],
            "seven_day_forecasts": [],
            "category_forecasts": [],
            "peak_ordering_periods": [],
            "low_demand_items": [],
            "potential_shortages": [],
        }

    today = today_college()
    end_d = today + timedelta(days=horizon_days)
    fc_rows = list(
        db.scalars(
            select(DemandForecast)
            .where(
                DemandForecast.model_id == active_model.id,
                DemandForecast.forecast_date > today,
                DemandForecast.forecast_date <= end_d,
            )
            .order_by(DemandForecast.forecast_date.asc())
        ).all()
    )
    food_ids = list({r.food_item_id for r in fc_rows})
    foods = (
        {f.id: f for f in db.scalars(select(FoodItem).where(FoodItem.id.in_(food_ids))).all()}
        if food_ids
        else {}
    )
    cat_ids = list({f.category_id for f in foods.values() if f.category_id})
    cats = (
        {c.id: c.name for c in db.scalars(select(FoodCategory).where(FoodCategory.id.in_(cat_ids))).all()}
        if cat_ids
        else {}
    )

    tomorrow = today + timedelta(days=1)
    next_day = []
    agg_7d: dict[UUID, dict[str, Any]] = {}
    cat_agg: dict[str, float] = {}
    for r in fc_rows:
        fi = foods.get(r.food_item_id)
        fname = fi.name if fi else "Food Item"
        cname = cats.get(fi.category_id, "Uncategorized") if fi else "Uncategorized"
        pred_f = float(r.predicted_quantity)
        low_f = float(r.lower_bound)
        high_f = float(r.upper_bound)

        if r.forecast_date == tomorrow:
            next_day.append(
                {
                    "food_item_id": str(r.food_item_id),
                    "food_item_name": fname,
                    "category_name": cname,
                    "forecast_date": r.forecast_date.isoformat(),
                    "predicted_quantity": round(pred_f, 1),
                    "lower_bound": round(low_f, 1),
                    "upper_bound": round(high_f, 1),
                    "data_classification": "ai_predicted",
                }
            )
        entry = agg_7d.setdefault(
            r.food_item_id,
            {
                "food_item_id": str(r.food_item_id),
                "food_item_name": fname,
                "category_name": cname,
                "total_predicted_quantity": 0.0,
                "total_lower_bound": 0.0,
                "total_upper_bound": 0.0,
                "daily": [],
            },
        )
        entry["total_predicted_quantity"] = round(entry["total_predicted_quantity"] + pred_f, 1)
        entry["total_lower_bound"] = round(entry["total_lower_bound"] + low_f, 1)
        entry["total_upper_bound"] = round(entry["total_upper_bound"] + high_f, 1)
        entry["daily"].append(
            {
                "date": r.forecast_date.isoformat(),
                "predicted_quantity": round(pred_f, 1),
                "lower_bound": round(low_f, 1),
                "upper_bound": round(high_f, 1),
            }
        )
        cat_agg[cname] = round(cat_agg.get(cname, 0.0) + pred_f, 1)

    next_day.sort(key=lambda x: -x["predicted_quantity"])
    seven_day_list = sorted(agg_7d.values(), key=lambda x: -x["total_predicted_quantity"])
    low_demand = sorted(agg_7d.values(), key=lambda x: (x["total_predicted_quantity"], x["food_item_name"]))[:10]
    cat_list = [{"category_name": k, "predicted_quantity_7d": v} for k, v in sorted(cat_agg.items(), key=lambda kv: -kv[1])]

    tz = get_college_tz()
    since_30 = datetime.now(timezone.utc) - timedelta(days=30)
    ord_ts = db.scalars(
        select(Order.created_at).where(
            Order.canteen_id == canteen_id,
            Order.payment_status == "CONFIRMED",
            Order.created_at >= since_30,
        )
    ).all()
    hr_counts: dict[int, int] = {}
    for ts in ord_ts:
        dt_u = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
        hr = dt_u.astimezone(tz).hour
        hr_counts[hr] = hr_counts.get(hr, 0) + 1
    peak_periods = [
        {"hour": f"{h:02d}:00", "historical_orders_30d": c}
        for h, c in sorted(hr_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:6]
    ]

    potential_shortages: list[dict[str, Any]] = []
    if agg_7d:
        recipes = list(
            db.scalars(
                select(Recipe).where(Recipe.food_item_id.in_(list(agg_7d.keys())), Recipe.is_verified.is_(True))
            ).all()
        )
        if recipes:
            rec_by_id = {r.id: r for r in recipes}
            ing_needed: dict[UUID, Decimal] = {}
            for req in db.scalars(select(RecipeIngredient).where(RecipeIngredient.recipe_id.in_(list(rec_by_id.keys())))).all():
                rec = rec_by_id[req.recipe_id]
                f_tot = Decimal(str(agg_7d[rec.food_item_id]["total_predicted_quantity"]))
                needed = ((req.quantity_required * f_tot) / Decimal(max(1, rec.yield_portions))).quantize(Decimal("0.001"))
                ing_needed[req.ingredient_id] = ing_needed.get(req.ingredient_id, Decimal("0.000")) + needed
            if ing_needed:
                invs = db.execute(
                    select(InventoryItem, Ingredient)
                    .join(Ingredient, Ingredient.id == InventoryItem.ingredient_id)
                    .where(
                        InventoryItem.canteen_id == canteen_id,
                        InventoryItem.ingredient_id.in_(list(ing_needed.keys())),
                    )
                ).all()
                for inv, ing in invs:
                    req_q = ing_needed.get(inv.ingredient_id, Decimal("0.000"))
                    usable = get_unexpired_stock_quantity(db, inv, exclude_reserved=True)
                    if usable < req_q:
                        potential_shortages.append(
                            {
                                "inventory_item_id": str(inv.id),
                                "ingredient_name": ing.name,
                                "unit": inv.unit,
                                "usable_stock": str(usable),
                                "forecasted_7d_requirement": str(req_q),
                                "projected_deficit": str((req_q - usable).quantize(Decimal("0.001"))),
                                "data_classification": "ai_predicted",
                            }
                        )
                potential_shortages.sort(key=lambda x: -float(x["projected_deficit"]))

    return {
        "canteen_id": str(canteen_id),
        "canteen_name": canteen.name,
        "status": "ok",
        "data_classification": "ai_predicted",
        "disclaimer": "All demand forecasts are AI predictions trained on verified historical sales and carry statistical uncertainty intervals.",
        "active_model": {
            "id": str(active_model.id),
            "model_version": active_model.model_version,
            "algorithm": active_model.algorithm,
            "historical_days_used": active_model.historical_days_used,
            "sample_rows": active_model.sample_rows,
            "mae": float(active_model.mae) if active_model.mae is not None else None,
            "rmse": float(active_model.rmse) if active_model.rmse is not None else None,
            "mape": float(active_model.mape) if active_model.mape is not None else None,
            "baseline_mae": float(active_model.baseline_mae) if active_model.baseline_mae is not None else None,
            "baseline_rmse": float(active_model.baseline_rmse) if active_model.baseline_rmse is not None else None,
            "comparison_metrics": active_model.comparison_metrics_json or {},
            "trained_at": active_model.trained_at.isoformat() if active_model.trained_at else None,
        },
        "next_day_forecasts": next_day,
        "seven_day_forecasts": seven_day_list,
        "category_forecasts": cat_list,
        "peak_ordering_periods": peak_periods,
        "low_demand_items": low_demand,
        "potential_shortages": potential_shortages,
    }


def evaluate_past_forecasts(db: Session, canteen_id: UUID, *, lookback_days: int = 30) -> dict[str, Any]:
    """Compare previously generated DemandForecast rows for elapsed dates against actual confirmed orders."""
    canteen = db.get(Canteen, canteen_id)
    if not canteen:
        raise HTTPException(status_code=404, detail="Canteen not found")

    tz = get_college_tz()
    today = today_college()
    since_d = today - timedelta(days=max(1, min(lookback_days, 180)))

    stored_evals = list(
        db.scalars(
            select(ForecastEvaluation)
            .where(ForecastEvaluation.canteen_id == canteen_id)
            .order_by(ForecastEvaluation.created_at.desc())
            .limit(30)
        ).all()
    )
    past_forecasts = list(
        db.scalars(
            select(DemandForecast).where(
                DemandForecast.canteen_id == canteen_id,
                DemandForecast.forecast_date >= since_d,
                DemandForecast.forecast_date < today,
            )
        ).all()
    )

    realized_metrics: dict[str, Any]
    if not past_forecasts:
        realized_metrics = {
            "status": "no_elapsed_forecasts",
            "evaluated_pairs": 0,
            "mae": None,
            "rmse": None,
            "mape": None,
            "message": "No past forecast dates have completed yet for realized-vs-predicted comparison.",
        }
    else:
        s_dt = datetime.combine(since_d, time.min, tzinfo=tz)
        e_dt = datetime.combine(today - timedelta(days=1), time.max, tzinfo=tz)
        actual_rows = db.execute(
            select(Order.created_at, OrderItem.food_item_id, OrderItem.quantity)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(
                Order.canteen_id == canteen_id,
                Order.payment_status == "CONFIRMED",
                Order.created_at >= s_dt,
                Order.created_at <= e_dt,
                OrderItem.food_item_id.is_not(None),
            )
        ).all()
        actual_map: dict[tuple[UUID, date], float] = {}
        for ts, fid, qty in actual_rows:
            dt_u = ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts
            d_loc = dt_u.astimezone(tz).date()
            actual_map[(fid, d_loc)] = actual_map.get((fid, d_loc), 0.0) + float(qty or 0)

        y_true = [actual_map.get((fc.food_item_id, fc.forecast_date), 0.0) for fc in past_forecasts]
        y_pred = [float(fc.predicted_quantity) for fc in past_forecasts]
        mae, rmse, mape, _std = _compute_metrics(y_true, y_pred)
        realized_metrics = {
            "status": "ok",
            "evaluated_pairs": len(past_forecasts),
            "mae": mae,
            "rmse": rmse,
            "mape": mape,
            "message": None,
        }

    return {
        "canteen_id": str(canteen_id),
        "canteen_name": canteen.name,
        "lookback_days": lookback_days,
        "data_classification": "calculated",
        "realized_vs_predicted": realized_metrics,
        "training_evaluations": [
            {
                "id": str(e.id),
                "model_id": str(e.model_id),
                "evaluation_date": e.evaluation_date.isoformat() if e.evaluation_date else None,
                "mae": float(e.mae) if e.mae is not None else None,
                "rmse": float(e.rmse) if e.rmse is not None else None,
                "mape": float(e.mape) if e.mape is not None else None,
                "evaluated_items_count": e.evaluated_items_count,
                "notes": e.notes,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in stored_evals
        ],
    }
