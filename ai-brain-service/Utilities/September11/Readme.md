# Sep 11

## Collect the data from Sep 2 and Sep 7 of 11 experiments witht the following features for raw
  
1. **Audit & Metadata** (Kept in CSV for human review, excluded from training)
2. **Global Cluster Telemetry** (System-wide lens)
3. **Caller Telemetry** (`order_service` lens)
4. **Local Target & Breaker Telemetry** (Normalized connection lens)

---

### The 21 Columns of Your Raw CSV File

| # | Column Name | Source / Type | Description / Role |
|---|---|---|---|
| 1 | `timestamp` | System (Unix) | Audit / Time-series sorting |
| 2 | `UTC Datetime` | System (ISO) | Human inspection |
| 3 | `Local Datetime` | System (ISO) | Human inspection |
| 4 | `experiment_id` | Metadata | e.g., `test_spike_01` (prevents train/test leakage) |
| 5 | `cb_name` | Metadata | e.g., `paymentService` *(kept for audit, dropped from $X$)* |
| 6 | `target_service` | Metadata | e.g., `payment_service` *(kept for audit, dropped from $X$)* |
| **Global Context** | | | |
| 7 | `cluster_cpu` | Prometheus | Average CPU usage across all 4 services |
| 8 | `cluster_mem` | Prometheus | Average JVM memory utilization across all services |
| 9 | `gateway_throughput` | Prometheus | Inbound QPS entering `gateway_service` |
| 10 | `cluster_error_rate` | Prometheus | Total cluster 5xx errors / Total cluster requests |
| **Caller Context** | | | |
| 11 | `caller_cpu` | Prometheus | CPU usage of `order_service` |
| 12 | `caller_mem` | Prometheus | Memory utilization of `order_service` |
| **Local Target Context** | | | |
| 13 | `target_cpu` | Prometheus | CPU usage of target (`inventory` or `payment`) |
| 14 | `target_mem` | Prometheus | Memory utilization of target |
| 15 | `target_latency` | Prometheus | Raw latency of target in milliseconds |
| 16 | `feat_threshold` | Config | SLA threshold (e.g., 300ms for inventory, 1500ms for payment) |
| 17 | `latency_ratio` | Engineered | $\frac{\text{target\_latency}}{\text{feat\_threshold}}$ *(scale-free feature)* |
| 18 | `target_error_rate` | Prometheus | 5xx rate / total requests for target (0.0 to 1.0) |
| 19 | `cb_failure_rate` | Prometheus | Resilience4j calculated failure rate (0 to 100) |
| 20 | `cb_state` | Prometheus | Breaker state (0=closed, 1=half_open, 2=open) |
| **Target Label ($y$)** | | | |
| 21 | **`status`** | Label Logic | **`'Healthy'`, `'Degraded'`, or `'Failed'`** |

---
## Validation Datasets

### What to Look For (The 3 Critical Red Flags)

#### 1. Flatline at 0.0 (`std = 0.00`)
* **What it means:** A metric was stuck at `0.0` across all 10 experiments.
* **Common culprit:** An Otel label mismatch. For example, if `payment_service` was logged in Prometheus with `application="payment-service"` (hyphen) instead of `application="payment_service"` (underscore), Prometheus quietly returns nothing, which `.fillna(0.0)` turns into a flat zero.
* **Why it hurts the model:** The tree will assign zero importance to that feature.

#### 2. Class Imbalance (e.g., 96% Healthy, 3% Degraded, 1% Failed)
* **What it means:** The chaos injection or load spike in your experiments only lasted a few seconds.
* **Why it hurts the model:** Random Forest might achieve 96% accuracy simply by guessing "Healthy" every single time, missing the exact moment a circuit breaker should trip.
* **The fix:** Use `class_weight='balanced'` in your training pipeline (which we included in the Colab code) to penalize missed "Failed" states.

#### 3. Zero Errors on "Failed" States
* Look at the table produced in **[CHECK 5]**:
  * For **Healthy**: `latency_ratio` should be `< 0.6` and `target_error_rate` should be close to `0.0`.
  * For **Degraded**: `latency_ratio` should hover between `0.6` and `1.0`.
  * For **Failed**: `latency_ratio > 1.0` or `target_error_rate > 0.5`.
* If you see high latency labeled as "Healthy", or normal latency labeled as "Failed", your labeling threshold logic in `_assign_status` needs tuning.
## Data Cleaning
### **cb_failure_rate report -1**

This is **standard Resilience4j design**, not a bug:

* **The Cause (`minimumNumberOfCalls`):**
  Resilience4j uses a sliding window (e.g., 50 or 100 requests). Until the service receives enough requests to satisfy `minimumNumberOfCalls`, the failure rate **cannot be calculated mathematically**.
* **Why it returns `-1`:**
  Instead of guessing `0%`, Resilience4j intentionally exposes `-1.0` to Prometheus to mean:  
  *“Insufficient traffic in sliding window / Not yet calculated.”*
* **Why it changed to `0` after a few minutes:**
  As test traffic accumulated and the sliding window filled past `minimumNumberOfCalls`, Resilience4j officially calculated the failure rate: 0 errors out of $N$ calls = `0.0%`.

#### ⚠️ Machine Learning Warning for `-1`:
A Random Forest does not know `-1` means "warming up"—it treats `-1` as a continuous number smaller than `0`. If you leave `-1` in your training data, the model might create weird rules like `if cb_failure_rate < -0.5: Healthy`.

**Fix:** In your cleaning step, map all negative failure rates to `0.0`:
```python
# Replace Resilience4j warmup value (-1.0) with 0.0
df["cb_failure_rate"] = df["cb_failure_rate"].clip(lower=0.0)

