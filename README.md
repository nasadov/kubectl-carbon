# Kubectl Carbon

## Introduction

`kubectl-carbon` is a `kubectl` plugin that helps schedule deployments in a Kubernetes cluster with carbon awareness. It works together with:
* an external [carbon-aware placement algorithm](https://github.com/nasadov/carbon-aware-orchestrator) that provides placement info for each Pod.
* k8s scheduler plugins at the extension points `PreEnqueue` and `Score` that use the placement info (see [here](https://gitlab.fbk.eu/fogatlas-k8s/scheduler-plugins)).

More documentation can be found [here](./docs/Proposal.pdf)

## Setup and Usage

This setup is based on KWOK. 
* Note that deletion of pods is made via `KWOK Stages`. Currently, we defined 12 Stages corresponding to the deletion after one hour, two hours, ... twelve hours. If needed, more stages can be added to `./k8s/kwok-config.yaml`.
* Note also that for speeding up the execution a shrink time factor has been defined in the `kubectl-carbon` executable: by default the time is divided by 60. This value can be changed on the command line.
* **Important:** All duration values in `kwok-config.yaml` are hardcoded and do not automatically adjust with the shrink factor. These include:
  * Pod durations: `duration-1h` pods run for 60,000ms (1 real minute) with shrink factor of 60
  * Node heartbeat intervals: Default is 600,000ms (10 real minutes) with shrink factor of 60
  * Pod deletion delays: Default is 5,000ms (5 real seconds) with shrink factor of 60
  * Node lease durations: Default is 200 seconds with shrink factor of 60
  * If you change the shrink factor, use `./scripts/update_kwok_durations.sh` to update all timing values

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

This project includes tools to help evaluate the carbon-aware scheduler against different algorithms and collect metrics.

### Prerequisites

1.  **Complete Basic Setup:** Follow the steps in the "Setup and Usage" section to build `kubectl-carbon`, set up the VM with Vagrant, and configure the KWOK cluster (`make kwok`).
2.  **Carbon-Aware Algorithm:** Ensure the external carbon-aware placement algorithm server is running. You can typically start it from the `bin` directory:
    ```bash
    cd /path/to/carbon-aware-orchestrator/bin # Adjust path if needed
    ./carbon-aware & # Run in the background
    ```
3.  **Forecast File:** Make sure the carbon intensity forecast file (e.g., `all_forecasts.json`) is available at the location expected by the `collect_metrics.py` script (default: `/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/all_forecasts.json`) or specify its path using the `--forecast-file` option when running benchmarks.
4.  **Output Directories:** The system will automatically create necessary output directories, including `/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/experiments/` for vanilla placement CSV files.
5.  **Python Dependencies:** Ensure required Python packages (`matplotlib`, `numpy`) are installed for metrics analysis and plotting:
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
   
**Important Note on Time Scaling:**
   When changing the `--shrink-factor` from the default value of 60, you must also update the pod duration times in KWOK to maintain consistent simulated timing and restart the KWOK cluster. Use the provided script:
   
   ```bash
   # Example: If using shrink-factor 120 (1 real second = 2 simulation minutes):
   # This will update the config AND recreate the KWOK cluster
   ./scripts/apply_kwok_settings.sh --shrink-factor 120
   
   # If you only want to update the config without restarting:
   ./scripts/update_kwok_durations.sh --shrink-factor 120
   # Then manually restart KWOK later with:
   make kwok
   ```
   
   **IMPORTANT**: Changes to KWOK timing settings only take effect when the KWOK cluster is completely recreated. Simply applying the updated configuration is not sufficient. For detailed information about pod durations and timing, see [Pod Duration Documentation](./docs/pod_durations.md).

**How it Works:**

   The `run_benchmark.sh` script performs these steps:
   1.  Creates an experiment directory under `benchmark_results/`.
   2.  Starts the `applyWorkloadAll.sh` script to simulate applying workloads over time according to the `--shrink-factor` and `--call-interval`. This script logs performance data to `performance.log`.
   3.  Starts the `collect_metrics.py` script (in the background) to periodically gather data (node usage, pod status, carbon intensity, etc.) based on the `--interval`. This script saves raw data to the `raw_data/` subdirectory and logs its activity to `collection.log`.
   4.  After applying all workloads, continues collecting metrics for 12 additional simulation hours to allow all pods to complete their execution.
   5.  Waits for the user to stop data collection with Ctrl+C when ready.
   6.  Runs `analyze_metrics.py` to process the collected `raw_data` and generate summary `results.json` and plots in the `plots/` directory.
   7.  Runs `perf_metrics_analyzer.py` to analyze `performance.log` and save results to the `raw_data/` directory with plots moved to the `plots/performance/` directory.

**Understanding Simulation Time and KWOK Durations:**

   The benchmark system works with two time domains:
   1.  **Real time**: Actual wall clock time that passes during the benchmark.
   2.  **Simulation time**: Accelerated time within the simulation (real time × shrink factor).
   
   Several timing values in the KWOK configuration need to be adjusted when the shrink factor changes:
   
   1. **Pod durations** are defined in the KWOK configuration file (`k8s/kwok-config.yaml`) as labels:
      - `duration-1h`: Pods intended to run for 1 simulation hour
      - `duration-2h`: Pods intended to run for 2 simulation hours
      - And so on...
   
   2. **Node heartbeat intervals** control how often simulated nodes report their status
   
   3. **Pod deletion delays** control how quickly pods are deleted when terminated
   
   4. **Node lease durations** control how long node leases are valid in the cluster
   
   All these time values need to be adjusted by the shrink factor with formulas like:
   ```
   duration_ms = (time_in_simulation_units × 1000) / shrink_factor
   ```
   
   For example, with the default shrink factor of 60:
   - A `duration-1h` pod runs for 60,000ms = 1 real minute (representing 1 simulation hour)
   - Node heartbeats occur every 10 real minutes (representing 10 simulation hours)
   
   The `update_kwok_durations.sh` script handles all these calculations automatically when you change the shrink factor.

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
*   `results.json`: Summary of key metrics (total carbon, average latency, etc.).
*   `raw_data/`: Contains detailed time-series data in CSV and JSON formats (e.g., `nodes.csv`, `pods.json`, `carbon.csv`, `performance_metrics.csv`). **This is the primary output.**
*   `plots/`: Contains generated graphs visualizing the collected metrics:
    *   `plots/carbon/`: Carbon-related metrics (e.g., `carbon_intensity.png`, `cluster_power.png`)
    *   `plots/nodes/`: Node utilization metrics
    *   `plots/performance/`: Performance-related plots (e.g., `scheduling_latency.png`, `combined_performance.png`)
    *   `plots/comparison/`: Comparison plots if applicable

### Vanilla Placement CSV Generation

In addition to the experiment-specific data in the `raw_data/` directory, the system generates vanilla placement CSV files for comparison purposes in the CAO framework (server-side without considering the kwok cluster). These files contain scheduling decisions made by the default Kubernetes scheduler and are saved to:

```
/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/experiments/vanilla_placement_session.csv
```

The vanilla placement CSV contains the following columns:
- `pod_id`: Unique identifier for each pod
- `node_id`: ID of the node where the pod was scheduled
- `start_slot`: Time slot when the pod started
- `duration`: How long the pod ran
- `cpu_request`: CPU resources requested by the pod
- `ram_request`: Memory resources requested by the pod

**Retroactive CSV Generation:**
You can generate vanilla placement CSV files from existing experiment data using:

```bash
cd /root/carbon/scripts
python3 collect_metrics.py --generate-csv-only /path/to/experiment/raw_data/
```

This is useful for analyzing historical experiment data or generating comparison CSVs from previously collected benchmark results.

### Manual Steps and Other Scripts (Advanced)

While `run_benchmark.sh` is the recommended way, you might use other scripts directly:

*   `collect_metrics.py`: Run directly to collect metrics without applying workloads or performing analysis automatically. Requires manual start/stop (Ctrl+C). Also supports `--generate-csv-only` flag for retroactive CSV generation from existing raw data.
*   `applyWorkloadAll.sh`: Applies all workload files sequentially based on shrink factor and call interval. After all workloads are deployed, it continues for 12 additional simulation hours to collect metrics on running pods.
*   `applyWorkloadPerHour.sh`: An alternative way to apply workloads, potentially useful for different simulation scenarios.
*   `analyze_metrics.py`: Run manually to re-analyze data from an existing `raw_data` directory. This script now automatically triggers performance metrics analysis as well.
*   `perf_metrics_analyzer.py`: Run manually to analyze a `performance.log` file if you need to run the performance analysis separately.
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


