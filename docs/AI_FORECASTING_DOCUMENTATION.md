# CollegeBites — AI Demand Forecasting & Assistant Documentation

## 1. AI Demand Forecasting Pipeline (`/api/v1/forecasting`)
### Data Sources & Minimum Data Gate
- **Source:** Strictly verified confirmed historical orders (`Order.payment_status == 'CONFIRMED'`) joined with `OrderItem`, plus campus calendar context (`CollegeHoliday`, `CollegeEvent`).
- **Minimum Data Requirement:** At least **7 distinct historical sales days** (`MIN_HISTORICAL_DAYS = 7`). When fewer than 7 days exist, the API returns `status: "insufficient_data"` and `"Insufficient historical data to generate a reliable forecast."` — it never fabricates predictions.

### Feature Engineering (Zero Future Leakage)
All features for date $t$ are strictly causal (computed exclusively from dates $< t$):
- `item_code`, `day_of_week`, `is_weekend`, `day_of_month`, `is_holiday`, `is_event`
- `lag_1` (sales on $t-1$), `lag_7` (sales on $t-7$), `rolling_7_mean`, `rolling_14_mean`

### Chronological Validation & Model Selection
- **Split:** Strict chronological 80% train / 20% validation split by unique sales dates (no random shuffling).
- **Candidate Models Evaluated:**
  1. `rolling_7d_baseline` (causal 7-day moving average benchmark)
  2. `ridge_regression` (L2-regularized linear model, $\alpha = 1.0$)
  3. `random_forest` (bagged CART decision tree ensemble)
  4. `gradient_boosting` (sequential residual-boosted CART trees)
- **Runtime Portability:** Uses `scikit-learn` natively on Linux/Docker/Vercel and seamlessly falls back to mathematically exact pure-Python Ridge, Bagged CART, and Boosted CART implementations on Windows environments where Application Control blocks native SciPy Fortran DLLs.
- **Evaluation & Realized Tracking:** Real holdout **MAE**, **RMSE**, and **MAPE** (excluding zero-actual denominators) persisted per version in `ForecastModel` and `ForecastEvaluation`. Outlier protection winsorizes extreme item spikes at `Q3 + 3.0 * IQR` (when `>= 8` positive days exist) and excludes zero-sales holiday closures from distorting weekday baselines. `GET /api/v1/forecasting/canteens/{canteen_id}/evaluations` compares past elapsed `DemandForecast` rows against actual realized orders.
- **Uncertainty Bands:** Multi-step 1-to-14-day recursive predictions include honest prediction intervals (`lower_bound = max(0, pred - 1.28 * sigma)`, `upper_bound = pred + 1.28 * sigma`), explicitly tagged `data_classification = "ai_predicted"`.
- **Operational Integration:** Feeds projected 7-day verified-recipe ingredient shortages into Automated Reordering and displays AI forecasts in a separate column from confirmed orders on the Production Planning dashboard (eliminating double-counting).

## 2. Controlled Role-Aware AI Canteen Assistant (`/api/v1/ai-assistant`)
- **Access Control & Role Output Filtering:** Restricted to authenticated staff/admin/inspector roles holding `ai_assistant:use`; customers receive `HTTP 403`. Staff assigned to a canteen cannot query other canteens or reuse conversations across canteens. Non-finance roles (`kitchen_staff`, `food_safety_inspector`) receive item/wastage quantities only without `₹` revenue or financial loss amounts, and `food_safety_inspector` is blocked from querying demand forecasts.
- **Strictly Read-Only Action Blocking:** Detects and blocks any write/mutate intent (PO creation/approval, vendor payment/money transfer, refunds, order/batch cancellation, menu/user deactivation, recipe/price/inventory/production edits, recall approvals, payment confirmation, broadcasts, SQL commands), returning `data_classification: "policy_restricted"` and recording `blocked_action_attempted = true` in `AIAssistantAuditLog`.
- **Grounded Provenance:** Every response invokes approved parameterized backend services, supports explicit `YYYY-MM-DD` date parsing, classifies derived AOV/margin/accuracy answers as `calculated`, and outputs `answer`, `data_source`, `date_range`, `last_updated`, `data_classification`, `limitations`, `tools_invoked`, and `supporting_data`, persisted in `AIAssistantConversation` and `AIAssistantMessage`.
