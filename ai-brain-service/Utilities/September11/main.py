import argparse
from experiment import load_default_registry
from collector import PrometheusCollector

class ExperimentPipelineRunner:
    """Orchestrates the execution of selected experiments."""

    def __init__(self, registry=None, collector=None):
        self.registry = registry or load_default_registry()
        self.collector = collector or PrometheusCollector()

    def run(self, selection_str: str) -> None:
        selected_experiments = self.registry.parse_selection(selection_str)
        if not selected_experiments:
            print("No valid experiments selected.")
            return

        print(f"Found {len(selected_experiments)} experiment(s) to process: "
              f"{[exp.id for exp in selected_experiments]}")

        for exp in selected_experiments:
            self.collector.collect_and_save(exp)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Caller for Prometheus Experiment Collector")
    parser.add_argument(
        "--exp",
        type=str,
        default="1-5",
        help="Experiments to generate. Examples: '1-5', '1,3,5', '1-3,5,8'. Defaults to '1-5'."
    )
    args = parser.parse_args()

    pipeline = ExperimentPipelineRunner()
    pipeline.run(args.exp)


