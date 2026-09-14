from dataclasses import dataclass
from datetime import  datetime
from typing import Dict, List, Optional



@dataclass
class Experiment:
    """Represents the configuration and metadata for a single experiment."""
    id:int
    name:str
    start_time_str: str
    end_time_str: str
    filename: Optional[str] = None
    threshold: float = 1500.0

    @property
    def start_dt(self) -> datetime:
        return datetime.strptime(self.start_time_str, '%Y-%m-%d %H:%M:%S')

    @property
    def end_dt(self) -> datetime:
        return datetime.strptime(self.end_time_str, '%Y-%m-%d %H:%M:%S')

    @property
    def start_timestamp(self) -> int:
        return int(self.start_dt.timestamp())

    @property
    def end_timestamp(self) -> int:
        return int(self.end_dt.timestamp())

    @property
    def output_filename(self) -> str:
        """Defaults to a standardized filename if none is provided."""
        if self.filename:
            return self.filename
        timestamp_str = datetime.now().strftime("%Y_%m_%d_%I_%M_%S_%p")
        return f"{self.name}_{timestamp_str}.csv"

class ExperimentRegistry:
    """Stores and manages experiment definitions."""

    def __init__(self):
        self._experiments: Dict[int, Experiment] = {}

    def register(self, experiment: Experiment) -> None:
        self._experiments[experiment.id] = experiment

    def get(self, exp_id: int)-> Optional[Experiment]:
        return self._experiments.get(exp_id)

    def parse_selection(self, selection_str: str) -> List[Experiment]:
        """
        Parses strings like '1-5', '1,3,5', or '1-3,5,7' and returns
        the corresponding list of registered Experiment objects.
        """
        selected_ids = set()
        for token in selection_str.split(","):
            token = token.strip()
            if "-" in token:
                start_s, end_s = token.split("-")
                start_i = int(start_s)
                end_i = int(end_s)
                print(f"start: {start_i}, end: {end_i}")
                selected_ids.update(range(int(start_s), int(end_s) +1))
            elif token.isdigit():
                selected_ids.add(int(token))

        resolved = []
        for exp_id in sorted(selected_ids):
            if exp_id in self._experiments:
                resolved.append(self._experiments[exp_id])
            else:
                print(f"[Warning] Experiment ID {exp_id} is not registered.")
        return resolved

# Define 1 to 11 experiments here
def load_default_registry() -> ExperimentRegistry:
    registry = ExperimentRegistry()

    experiments_data = [
        Experiment(1, "exp001_baseline", "2026-09-01 13:41:00", "2026-09-01 13:51:00", "", 1000),
        Experiment(2, "exp002_high_load", "2026-09-01 14:09:00", "2026-09-01 14:20:00", "", 1000),
        Experiment(3, "exp003_degraded_strict", "2026-09-01 15:55:00", "2026-09-01 16:07:00", "", 1000),
        Experiment(4, "exp004_healthy_relaxed", "2026-09-01 17:28:00", "2026-09-01 17:38:00", "", 3000),
        Experiment(5, "exp005_degraded_long_term", "2026-09-01 19:59:00", "2026-09-01 20:11:00", "", 1000),
        Experiment(6, "exp006_hard_failure", "2026-09-01 20:40:00", "2026-09-01 20:51:00", "", 1000),
        Experiment(7, "exp007_recovery_halfopen", "2026-09-01 22:14:21", "2026-09-01 22:26:00", "", 1000),
        Experiment(8, "exp008_infrastructure_failure", "2026-09-01 22:45:00", "2026-09-01 22:56:00", "", 1000),
        Experiment(9, "exp009_transition_study", "2026-09-01 23:12:00", "2026-09-01 23:23:00", "", 2000),
        Experiment(10, "exp010_compound_failure", "2026-09-01 23:39:00", "2026-09-01 23:50:00", "", 1000),
        Experiment(11, "exp011_validation", "2026-09-07 14:21:17", "2026-09-07 14:26:30", "", 1500),

    ]

    for exp in experiments_data:
        registry.register(exp)

    return registry