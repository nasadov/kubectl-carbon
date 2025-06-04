# Performance Metrics in Carbon-Aware Scheduler

This document explains the performance metrics tracked by the `perf_metrics_analyzer.py` script during carbon-aware scheduling operations.

## Overview

The carbon-aware scheduler tracks execution times for five key functions during each workload timeslot processing. These metrics help identify bottlenecks and optimize the scheduling pipeline.

## Tracked Functions

### 1. LoadInfra
**Purpose**: Loads the current Kubernetes cluster infrastructure information

**What it does**:
- Retrieves all available nodes in the cluster
- Collects node capacity, resources, and status information
- Creates an Infrastructure object containing the cluster snapshot

**Typical Duration**: 25-45ms  
**Performance Notes**: Consistently fast since cluster size is stable

---

### 2. GetWorkload
**Purpose**: Parses and loads the workload definition from YAML files

**What it does**:
- Reads the deployment manifest file (YAML)
- Extracts pod specifications, resource requirements, and constraints
- Converts YAML definitions into internal Workload data structures

**Typical Duration**: 13ms - 1.2s (varies with workload complexity)  
**Performance Notes**: Duration varies significantly based on the number and complexity of deployments in the YAML file

---

### 3. handlePlacement
**Purpose**: Calls the external carbon-aware placement algorithm to calculate optimal pod placement

**What it does**:
- Sends infrastructure and workload data to the carbon-aware algorithm server
- Waits for the algorithm to compute optimal placement decisions
- Receives back placement results with node assignments and scores

**Typical Duration**: 22ms - 13.4s (highly variable)  
**Performance Notes**: This is often the bottleneck step. Duration depends on:
- Algorithm complexity (heuristic vs global-optimal)
- Number of pods to place
- Infrastructure size
- Carbon intensity optimization complexity

---

### 4. savePlacementInfo
**Purpose**: Saves the placement decisions as Kubernetes custom resources for the scheduler to use

**What it does**:
- Creates or updates `FAPlacement` custom resources in the cluster
- Stores node scores and replica placement information
- Makes placement decisions available to the FogAtlas scheduler plugins

**Typical Duration**: 48ms - 3.6s (increases with number of placements)  
**Performance Notes**: Involves multiple Kubernetes API calls and scales with the number of deployments

---

### 5. deployment
**Purpose**: Actually creates the Kubernetes deployments in the cluster

**What it does**:
- Parses YAML deployment manifests
- Adds scheduling gates to prevent immediate scheduling
- Sets `timeToSchedule` labels based on placement results
- Creates deployments via Kubernetes API

**Typical Duration**: 13-57ms  
**Performance Notes**: Usually fast but depends on Kubernetes API responsiveness

## Performance Analysis

### Reading the Metrics
The performance analyzer generates:
- **CSV files**: `performance_metrics.csv` with iteration-by-iteration timing data
- **Individual plots**: One graph per function showing performance over time
- **Combined plots**: All functions on one graph (linear and log scale)

### Common Patterns
- **LoadInfra**: Stable performance across iterations
- **GetWorkload**: May spike with larger YAML files
- **handlePlacement**: Most variable; often dominates total execution time
- **savePlacementInfo**: Increases with deployment count
- **deployment**: Generally stable and fast

## Usage

The performance metrics are automatically collected during benchmark runs with carbon-aware algorithms (not vanilla). To analyze existing performance data:

```bash
cd /root/carbon/scripts
python3 perf_metrics_analyzer.py --log-file /path/to/performance.log --output-dir ./perf_analysis
```

This generates CSV data and visualization plots in the specified output directory.
