# Instantiate pipeline runner
from September09.collector import PrometheusCollector
from September09.experiment import load_default_registry
from September09.main import ExperimentPipelineRunner



runner = ExperimentPipelineRunner(
    registry=load_default_registry(),
    collector=PrometheusCollector(base_url="http://localhost:9090/api/v1/query_range")
)

# Run desired experiments
runner.run("1-11")

# Run desired experiments
# runner.run("1,3,5")
# Or a range
# runner.run("1-5")