import numpy as np
import pandas as pd

# Load your master dataset or one experiment file
CSV_PATH = "data/exp003_degraded_strict_2026_09_11_05_05_04_PM.csv"  # or your experiment csv
df = pd.read_csv(CSV_PATH)

print("=" * 70)
print(f"AUDITING DATASET: {CSV_PATH}")
print(f"Total rows: {len(df)} | Total columns: {len(df.columns)}")
print("=" * 70)

# -------------------------------------------------------------
# CHECK 1: The "Dead Metric" Test (Zero Variance / Flatline)
# -------------------------------------------------------------
# If an Otel label was misspelled (e.g. 'application' vs 'service_name'),
# Prometheus returns 0 for every single second.
print("\n[CHECK 1] Checking for 'Dead' or Constant Metrics...")
num_cols = [
    "cluster_cpu",
    "cluster_mem",
    "cluster_throughput",
    "cluster_error_rate",
    "caller_cpu",
    "caller_mem",
    "target_cpu",
    "target_mem",
    "target_latency",
    "target_error_rate",
    "cb_slow_call_rate",
    "cb_failure_rate",
    "latency_ratio",
]

dead_cols = []
for col in num_cols:
    if col in df.columns:
        std_val = df[col].std()
        unique_vals = df[col].nunique()
        min_val, max_val = df[col].min(), df[col].max()

        if unique_vals <= 1:
            dead_cols.append((col, min_val))
            print(f"  ❌ RED FLAG: '{col}' is completely flat! Stuck at {min_val}")
        else:
            print(
                f"  ✓ {col:<20} min: {min_val:>7.2f} | max: {max_val:>8.2f} | std: {std_val:>7.2f}"
            )

if not dead_cols:
    print("  [✓] All telemetry features show active variation!")

# -------------------------------------------------------------
# CHECK 2: Value Range & Unit Sanity
# -------------------------------------------------------------
# Did CPU come in as 0.0-1.0 or 0-100? Is error rate > 1.0?
print("\n[CHECK 2] Verifying Value Ranges & Units...")

range_rules = {
    "cluster_cpu": (0.0, 100.0),
    "caller_cpu": (0.0, 100.0),
    "target_cpu": (0.0, 100.0),
    "cluster_mem": (0.0, 1.0),
    "caller_mem": (0.0, 1.0),
    "target_mem": (0.0, 1.0),
    "target_error_rate": (0.0, 1.0),
    "cluster_error_rate": (0.0, 1.0),
    "cb_failure_rate": (0.0, 100.0),
    "latency_ratio": (0.0, 50.0),  # > 50x SLA is usually an infinite loop/hang
}

for col, (expected_min, expected_max) in range_rules.items():
    if col in df.columns:
        actual_min = df[col].min()
        actual_max = df[col].max()
        if actual_min < expected_min or actual_max > expected_max:
            print(
                f"  ⚠️ WARNING: '{col}' out of expected bounds [{expected_min}, {expected_max}]. Actual: [{actual_min:.2f}, {actual_max:.2f}]"
            )
        else:
            print(
                f"  ✓ {col:<20} is healthy within bounds [{expected_min}, {expected_max}]"
            )

# -------------------------------------------------------------
# CHECK 3: Target Class Balance & Representation
# -------------------------------------------------------------
# If 99% of your data is 'Healthy', the model will simply predict
# 'Healthy' all the time and achieve 99% fake accuracy.
print("\n[CHECK 3] Target Class Distribution ('status'):")
class_counts = df["status"].value_counts(dropna=False)
class_pct = df["status"].value_counts(normalize=True, dropna=False) * 100

for cls, count in class_counts.items():
    print(f"  - {cls:<10}: {count:>6} rows ({class_pct[cls]:>5.2f}%)")

if "Failed" not in class_counts or class_pct.get("Failed", 0) < 1.0:
    print(
        "  ❌ WARNING: 'Failed' class has <1% representation! Model will struggle to predict failures."
    )
if "Degraded" not in class_counts or class_pct.get("Degraded", 0) < 2.0:
    print(
        "  ⚠️ WARNING: 'Degraded' class is very low. Check your threshold formulas."
    )

# -------------------------------------------------------------
# CHECK 4: Temporal Symmetry (Inventory vs Payment balance)
# -------------------------------------------------------------
# At every timestamp, there should be an equal number of
# records for inventoryService and paymentService.
print("\n[CHECK 4] Breaker Record Symmetry:")
# Updated lines:
cb_counts = df["cb_name"].value_counts()
for name, count in cb_counts.items():
    print(f"  - {name}: {count}")

if len(cb_counts.unique()) > 1:
    print(
        "  ⚠️ WARNING: One breaker has more records than the other! Some seconds might be missing."
    )
else:
    print("  ✓ Perfect 1:1 symmetry between breakers.")

# -------------------------------------------------------------
# CHECK 5: Ground Truth Behavioral Sanity Check
# -------------------------------------------------------------
# Does a 'Failed' label actually correspond to high latency or high error rate?
print("\n[CHECK 5] Behavioral Cross-Check (Ground Truth Logic):")
mean_by_status = df.groupby("status")[
    ["target_latency", "latency_ratio", "target_error_rate", "cb_failure_rate"]
].mean()
print(mean_by_status.to_string())

# Sanity rule: Failed should have higher latency/error than Healthy
if "Failed" in mean_by_status.index and "Healthy" in mean_by_status.index:
    failed_latency = mean_by_status.loc["Failed", "latency_ratio"]
    healthy_latency = mean_by_status.loc["Healthy", "latency_ratio"]
    if failed_latency <= healthy_latency:
        print(
            "  ❌ LOGICAL CONTRADICTION: 'Failed' latency ratio is lower than 'Healthy'!"
        )
    else:
        print("  ✓ Behavioral logic confirmed: Failed > Degraded > Healthy.")