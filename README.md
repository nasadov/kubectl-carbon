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

## Running Experiments with the New Metrics System

The carbon-aware metrics system allows you to collect, analyze, and visualize detailed metrics about carbon intensity, energy usage, and scheduling performance. It uses real carbon intensity forecasts from `all_forecasts.json` to provide accurate environmental impact measurements.

### Experiment Setup

1. **Prerequisites**:
   - Complete the cluster setup steps from the previous sections
   - Ensure the carbon-aware scheduler is running
   - Make sure the `all_forecasts.json` file is available at its default location

2. **Running a Benchmark**:

   The `run_benchmark.sh` script simplifies metrics collection:
   
   ```bash
   # Basic usage with default parameters
   ./scripts/run_benchmark.sh
   
   # With custom parameters
   ./scripts/run_benchmark.sh --name my_experiment --interval 30 --duration 3600 --shrink-factor 60
   ```
   
   Important parameters:
   - `--name`: Custom name for the experiment (default: timestamp-based)
   - `--interval`: Metrics collection frequency in seconds (default: 60)
   - `--duration`: Total experiment duration in seconds (default: 3600)
   - `--shrink-factor`: Time acceleration factor (default: 1)
   - `--forecast-file`: Path to carbon forecasts (default: predefined path)

3. **Applying Workloads**:

   There are two methods for applying workloads during your experiments:
   
   a) **Apply all workloads at once** with time acceleration:
   ```bash
   # Usage: ./scripts/applyWorkloadAll.sh [shrink_factor] [call_interval]
   ./scripts/applyWorkloadAll.sh 60 3600
   ```
   This simulates 1 hour between workload applications while accelerating time by 60x.
   
   b) **Apply workloads hourly**:
   ```bash
   # Usage: ./scripts/applyWorkloadPerHour.sh [call_interval_seconds] [shrink_factor]
   ./scripts/applyWorkloadPerHour.sh 5 3600
   ```
   This waits 5 real seconds between applications while simulating 1 hour per second.

4. **Scheduling Gates Monitoring**:

   For experiments requiring pod scheduling at specific times:
   ```bash
   # Run in a separate terminal or as a background process
   ./scripts/checkSchedulingGates.sh
   ```
   
   This script monitors and removes scheduling gates when the scheduled time arrives.

### Analyzing Results

After an experiment, results are automatically saved to the `benchmark_results` directory:

1. **View Raw Data**:
   - Check the `raw_data` subfolder for detailed CSV and JSON files of all metrics
   - Review `benchmark.log` for experiment progress and any issues

2. **View Visualizations**:
   - The `plots` subfolder contains automatically generated graphs:
     - Carbon intensity over time
     - Power usage for the entire cluster
     - CPU utilization per node
     - Pod scheduling status
     - Node power draw

3. **Manual Analysis**:
   ```bash
   # Reanalyze existing data with different parameters
   python3 ./scripts/analyze_metrics.py --data-dir ./benchmark_results/my_experiment
   ```

### Example: Full Experiment Workflow

Here's a complete example demonstrating how to run an experiment with 60x time acceleration:

```bash
# Start carbon-aware algorithm in background
cd bin && ./carbon-aware &

# Start scheduling gate checker in background
./scripts/checkSchedulingGates.sh &

# Start metrics collection with 60x time acceleration
./scripts/run_benchmark.sh --name carbon_experiment_60x --shrink-factor 60 --interval 30 &

# Wait for collection to start
sleep 5

# Apply workloads with 60x acceleration and 1-hour intervals
./scripts/applyWorkloadAll.sh 60 3600

# When completed, view results
ls -la ./benchmark_results/carbon_experiment_60x/plots/
```

This workflow will collect metrics showing the impact of carbon-aware scheduling on your workloads, with visualizations of carbon intensity, power usage, and scheduling efficiency over time.

## License

Copyright 2025 Fondazione Bruno Kessler and Technische Universitaet Berlin

Licensed under the Apache License, Version 2.0 (the "License"); you may not use this
file except in compliance with the License. You may obtain a copy of the License
[here](http://www.apache.org/licenses/LICENSE-2.0).

Unless required by applicable law or agreed to in writing, software distributed under
the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
either express or implied. See the License for the specific language governing permissions
and limitations under the License.


