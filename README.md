# Kubectl Carbon

## Introduction

**kubectl-carbon** is a `kubectl` plugin able to trigger a carbon-aware scheduling of a bunch of deployments in a k8s cluster.  **kubectl-carbon** works in combination with:
* an external [carbon-aware placement algorithm](https://github.com/nasadov/carbon-aware-orchestrator) that provides placement info for each Pod.
* a couple of k8s scheduler plugins at the extension points `PreEnqueue` and `Score` that exploit the placement info provided (see [here](https://gitlab.fbk.eu/fogatlas-k8s/scheduler-plugins)).

More documentation can be found [here](./docs/Proposal.pdf)

## Setup and Usage

This setup is based on KWOK. 
* Note that deletion of pods is made via `KWOK Stages`. Currently, we defined 12 Stages corresponding to the deletion after one hour, two hours, ... twelve hours. If needed, more stages can be added to `./k8s/kwok-config.yaml`. 
* Note also that for speeding up the execution a shrink time factor has been defined in the `kubectl-carbon` executable: by default the time is divided by 60. This value can be changes on the command line but must be kept coherent with the deletion time defined in Stages. 

### With Carbon-aware algorithm and FogAtlas scheduler

In this case we use this manifest file `./experiments/microservices_carbon.yaml` whose deployments reference the `fogatlas` scheduler. 

1. Compile the `kubectl-carbon` executable:
   ```
   make build
   ```   
1. Create and provision the test VM with the all the required stuff:
   ```
   cd vagrant
   vagrant up
   ```
1. Login into the created VM
   ```
   vagrant ssh
   cd carbon
   ```
1. Copy the `kubectl-carbon` in `/usr/local/bin` and ensure that `kubectl` can see it:
   ```
   sudo cp ./bin/kubectl-carbon /usr/local/bin
   kubectl plugin list
   ```
1. Create the KWOK cluster and configure it
   ```
   make kwok
   ```   
1. Create an executable for the `carbon-aware` algorithm (see [here](https://github.com/nasadov/carbon-aware-orchestrator)), add the needed cofnfiguration files (e.g. `all_forecasts.json) and run it in a terminal   
   ```
   cd bin
   ./carbon-aware
   ```
1. Using `crontab` or similar tools (e.g. implementing a loop with a shell script), run periodically the following script that checks (and removes) the `scheduling gate` from each pod when $time_to_schedule < current_time$:
   ```
   ./scripts/checkSchedulingGates.sh
   ```
1. Invoke the carbon-aware plugin. Without parameter, the help message is printed out. Flags `-l, -a, -u, -w` are optional. Their default values are:
   `-l info -a carbon-aware - u localhost:50051 -w 60`. 
   ```
   # If kubectl-carbon has been registered to kubectl (i.e. copied to `/usr/local/bin`)
   kubectl carbon -f ./experiments/microservices_carbon.yaml -l [debug|info] -a [algorithm name] -u [algorithm url] -w [shrink time factor]
   # Otherwise
   ./bin/kubectl-carbon -f ./experiments/microservices_carbon.yaml -l [debug|info] -a [algorithm name] -u [algorithm url] -w [shrink time factor]
   ```
1.  Monitor the deployment:
   ```
   watch kubectl get pods -o wide
   ```  

### With vanilla k8s

Just to compare the results obtained with carbon-aware algorithm, we use `./experiments/microservices_default.yaml` that is the same as `./experiments/microservices_carbon.yaml` but without the reference to the `fogatlas` scheduler. Therefore, the default k8s scheduler is used. 

1. Create and provision the test VM with the all the required stuff:
   ```
   cd vagrant
   vagrant up
   ```
1. Login into the created VM
   ```
   vagrant ssh
   cd carbon
   ```
1. Create the KWOK cluster and configure it
   ```
   make kwok
   ```   
1. Invoke the deployment through kubectl:
   ```
   kubectl apply -f ./experiments/microservices_default.yaml 
   ```
1. Monitor the deployment:
   ```
   watch kubectl get pods -o wide
   ```

## Running Experiments and Collecting Metrics

This project includes a benchmarking system to evaluate the carbon-aware scheduler against different algorithms and collect detailed metrics.

### Prerequisites

1.  **Complete Basic Setup:** Follow the steps in the "Setup and Usage" section to build `kubectl-carbon`, set up the VM with Vagrant, and configure the KWOK cluster (`make kwok`).
2.  **Carbon-Aware Algorithm:** Ensure the external carbon-aware placement algorithm server is running. You can typically start it from the `bin` directory:
    ```bash
    cd /path/to/carbon-aware-orchestrator/bin # Adjust path if needed
    ./carbon-aware & # Run in the background
    ```
3.  **Forecast File:** Make sure the carbon intensity forecast file (e.g., `all_forecasts.json`) is available at the location expected by the `collect_metrics.py` script (default: `/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/all_forecasts.json`) or specify its path using the `--forecast-file` option when running benchmarks.
4.  **Python Dependencies:** Ensure required Python packages (`matplotlib`, `numpy`) are installed for metrics analysis and plotting:
    ```bash
    pip install matplotlib numpy
    ```

### Running a Benchmark Experiment

The `run_benchmark.sh` script automates the process of running an experiment, applying workloads, collecting metrics, and analyzing results.

**1. Choose an Algorithm:**

   The benchmark supports different scheduling approaches, controlled by the `--algorithm` flag:
   *   `vanilla`: Uses the default Kubernetes scheduler. Workloads are applied from the `workloads-vanilla/` directory.
   *   `heuristic`: Uses the carbon-aware scheduler with a heuristic placement algorithm. Workloads are applied from the `workloads/` directory. (Default)
   *   `global-optimal`: Uses the carbon-aware scheduler with a global optimal placement algorithm. Workloads are applied from the `workloads/` directory.

**2. Start the Benchmark:**

   Navigate to the `scripts` directory and execute `run_benchmark.sh`.

   ```bash
   cd /root/carbon/scripts

   # Example: Run with the 'heuristic' algorithm, 60x time acceleration,
   # collecting metrics every 30 seconds.
   ./run_benchmark.sh --name heuristic_test_60x_$(date +%Y%m%d_%H%M%S) --algorithm heuristic --shrink-factor 60 --interval 30 --call-interval 3600

   # Example: Run with the 'vanilla' algorithm for comparison
   ./run_benchmark.sh --name vanilla_test_60x_$(date +%Y%m%d_%H%M%S) --algorithm vanilla --shrink-factor 60 --interval 30 --call-interval 3600
   ```

   **Key Parameters:**
   *   `--name NAME`: A unique name for this experiment run. Results will be saved in `benchmark_results/NAME`. (Default: Timestamp-based name like `YYYYMMDD_HHMMSS_algorithm`)
   *   `--algorithm TYPE`: `vanilla`, `heuristic`, or `global-optimal`. (Default: `heuristic`)
   *   `--shrink-factor N`: Accelerates simulation time. `N=60` means 1 real second = 60 simulation seconds. (Default: `1`)
   *   `--interval SECONDS`: How often to collect metrics (real-time seconds). (Default: `60`)
   *   `--call-interval SECONDS`: Simulated time between applying workload timeslots. (Default: `3600`, representing 1 hour)
   *   `--output DIR`: Parent directory for results. (Default: `/root/carbon/benchmark_results`)
   *   `--forecast-file FILE`: Path to the carbon intensity forecast JSON.
   *   `--no-perf`: Disable detailed performance metric collection and analysis.

**How it Works:**

   The `run_benchmark.sh` script performs these steps:
   1.  Creates an experiment directory under `benchmark_results/`.
   2.  Starts the `applyWorkloadAll.sh` script (in the background if `--no-perf` is not used) to simulate applying workloads over time according to the `--shrink-factor` and `--call-interval`. This script logs performance data to `performance.log`.
   3.  Starts the `collect_metrics.py` script (in the background) to periodically gather data (node usage, pod status, carbon intensity, etc.) based on the `--interval`. This script saves raw data to the `raw_data/` subdirectory and logs its activity to `collection.log`.
   4.  Waits for the workload application and metrics collection to finish (or runs indefinitely until manually stopped with Ctrl+C if duration isn't implicitly limited by workloads).
   5.  Runs `analyze_metrics.py` to process the collected `raw_data` and generate summary `results.json` and plots in the `plots/` directory.
   6.  If performance metrics were captured, runs `perf_metrics_analyzer.py` to analyze `performance.log` and save results to the `perf_metrics/` directory.

**3. Monitor Progress (Optional):**

   You can monitor the experiment while it's running:
   *   Tail the logs: `tail -f /root/carbon/benchmark_results/YOUR_EXPERIMENT_NAME/*.log`
   *   Watch pod status: `watch kubectl get pods -o wide`

### Understanding the Results

After the script finishes (or is stopped), find the results in `/root/carbon/benchmark_results/YOUR_EXPERIMENT_NAME/`:

*   `experiment_config.json`: Configuration parameters used for the run.
*   `performance.log`: Log output from the workload application script (`applyWorkloadAll.sh`).
*   `collection.log`: Log output from the metrics collection script (`collect_metrics.py`).
*   `metrics_analysis.log`: Log output from the final analysis script (`analyze_metrics.py`).
*   `perf_analysis.log`: Log output from the performance analysis script (`perf_metrics_analyzer.py`).
*   `results.json`: Summary of key metrics (total carbon, average latency, etc.).
*   `raw_data/`: Contains detailed time-series data in CSV and JSON formats (e.g., `nodes.csv`, `pods.json`, `carbon.csv`). **This is the primary output.**
*   `plots/`: Contains generated graphs visualizing the collected metrics (e.g., `carbon_intensity.png`, `cluster_power.png`).
*   `perf_metrics/`: Contains performance analysis results if enabled (e.g., `performance_metrics.csv`, plots).

### Manual Steps and Other Scripts (Advanced)

While `run_benchmark.sh` is the recommended way, you might use other scripts directly:

*   `collect_metrics.py`: Run directly to collect metrics without applying workloads or performing analysis automatically. Requires manual start/stop (Ctrl+C).
*   `applyWorkloadAll.sh`: Applies all workload files sequentially based on shrink factor and call interval.
*   `applyWorkloadPerHour.sh`: An alternative way to apply workloads, potentially useful for different simulation scenarios.
*   `analyze_metrics.py`: Run manually to re-analyze data from an existing `raw_data` directory.
*   `perf_metrics_analyzer.py`: Run manually to analyze a `performance.log` file.
*   `checkSchedulingGates.sh`: If using workloads with specific scheduling times (gates), run this script in the background to manage them. `run_benchmark.sh` does *not* automatically run this.

## License

Copyright 2025 Fondazione Bruno Kessler and Technische Universitaet Berlin

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this
file except in compliance with the License. You may obtain a copy of the License
[here](http://www.apache.org/licenses/LICENSE-2.0).

Unless required by applicable law or agreed to in writing, software distributed under
the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
either express or implied. See the License for the specific language governing permissions
and limitations under the License.


