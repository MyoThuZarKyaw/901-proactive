import glob
import os
import numpy as np
import pandas as pd

# Directory where your experiment CSV files are saved
DATA_DIR = "./data"  # <--- Change this to your folder path if different
OUTPUT_FILE = "master_dataset.csv"

# The exact 21 columns expected in every experiment
EXPECTED_COLUMNS = [
    "timestamp",
    "caller_cpu",
    "caller_mem",
    "target_cpu",
    "target_mem",
    "target_latency",
    "target_error_rate",
    "cb_slow_call_rate",
    "cb_failure_rate",
    "cb_state",
    "cb_name",
    "target_service",
    "cluster_cpu",
    "cluster_mem",
    "cluster_throughput",
    "cluster_error_rate",
    "UTC Datetime",
    "Local Datetime",
    "feat_threshold",
    "latency_ratio",
    "status",
    "experiment_id",
]


def load_and_clean_file(filepath: str) -> pd.DataFrame:
    """Loads a single experiment CSV and applies necessary sanity cleanups."""
    df = pd.read_csv(filepath)

    # Drop any 'Unnamed: 0' index columns if present
    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]

    # Check for missing columns
    missing_cols = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing_cols:
        raise ValueError(
            f"File '{os.path.basename(filepath)}' is missing required columns: {missing_cols}"
        )

    # Reorder columns strictly
    df = df[EXPECTED_COLUMNS].copy()

    # 1. Replace infinities with NaN
    df.replace([np.inf, -np.inf], np.nan, inplace=True)

    # 2. Fix Resilience4j warmup value (-1.0 -> 0.0)
    # This prevents the ML model from misinterpreting -1.0 as a valid failure rate or slow call rate
    df["cb_slow_call_rate"] = df["cb_slow_call_rate"].clip(lower=0.0)
    df["cb_failure_rate"] = df["cb_failure_rate"].clip(lower=0.0)

    # 3. Fill any residual NaNs in numeric columns with 0.0
    num_cols = df.select_dtypes(include=[np.number]).columns
    df[num_cols] = df[num_cols].fillna(0.0)

    return df


def build_master_dataset():
    # Find all CSV files in the folder (excluding any existing master_dataset.csv)
    file_pattern = os.path.join(DATA_DIR, "*.csv")
    csv_files = [f for f in glob.glob(file_pattern) if not f.endswith(OUTPUT_FILE)]

    if not csv_files:
        print(f"[!] No experiment CSV files found in '{DATA_DIR}'. Check path!")
        return

    print(f"Found {len(csv_files)} experiment files in '{DATA_DIR}':")
    for f in sorted(csv_files):
        print(f"  - {os.path.basename(f)}")

    dataframes = []
    for f in sorted(csv_files):
        try:
            cleaned_df = load_and_clean_file(f)
            dataframes.append(cleaned_df)
            print(
                f"  [✓] Loaded {len(cleaned_df):>5} rows from {os.path.basename(f)}"
            )
        except Exception as e:
            print(f"  [❌] Error loading {os.path.basename(f)}: {e}")

    if not dataframes:
        print("[!] No valid DataFrames loaded. Aborting.")
        return

    # Combine all experiment dataframes
    master_df = pd.concat(dataframes, ignore_index=True)

    # Sort sequentially by timestamp and circuit breaker
    master_df.sort_values(by=["timestamp", "cb_name"], inplace=True)
    master_df.reset_index(drop=True, inplace=True)

    # Save to CSV
    master_df.to_csv(OUTPUT_FILE, index=False)

    print("\n" + "=" * 60)
    print("MASTER DATASET GENERATION COMPLETE")
    print("=" * 60)
    print(f"Total Rows Saved:    {len(master_df)}")
    print(f"Total Columns Saved: {len(master_df.columns)}")
    print(f"Saved to:            {OUTPUT_FILE}")

    # Dataset Summary
    print("\n--- Target Class Distribution ('status') ---")
    status_summary = master_df["status"].value_counts(dropna=False)
    status_pct = master_df["status"].value_counts(normalize=True) * 100
    for cls, count in status_summary.items():
        print(f"  {cls:<12}: {count:>6} rows ({status_pct[cls]:>5.2f}%)")

    print("\n--- Records per Experiment ID ---")
    print(master_df["experiment_id"].value_counts())

    print("\n--- Breaker Records ---")
    print(master_df["cb_name"].value_counts())

    # Sanity check: Ensure no -1.0 exists in cb_failure_rate
    min_failure_rate = master_df["cb_failure_rate"].min()
    print(f"\nMinimum cb_failure_rate in master file: {min_failure_rate} (Should be >= 0.0)")


if __name__ == "__main__":
    build_master_dataset()