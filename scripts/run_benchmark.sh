#!/bin/bash

#
# Copyright 2025 Fondazione Bruno Kessler.
#  
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#  
#      http://www.apache.org/licenses/LICENSE-2.0
#  
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#  
#

# Default values
EXPERIMENT_NAME="$(date +%Y%m%d_%H%M%S)"  # Just the timestamp part
COLLECTION_INTERVAL=60    # Collect metrics every X seconds
NAMESPACE="default"       # Default namespace to monitor
OUTPUT_DIR="/root/carbon/benchmark_results"
COMPARISON_MODE=false     # Whether to run a comparison between schedulers
SHRINK_FACTOR=1          # Default shrink factor is 1 (no time shrinking)
FORECAST_FILE="/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/all_forecasts.json"
ALGORITHM="heuristic"    # Default algorithm: options are vanilla, heuristic, global-optimal
CALL_INTERVAL=3600       # Default interval between workload submissions (3600 simulation seconds = 1 hour)
# Base directories for workloads
WORKLOADS_BASE_DIR="/root/carbon-aware-orchestrator/pkg/carbon-aware"
# Always capture and analyze performance metrics
CAPTURE_PERF_METRICS=true
AUTO_STOP=false
NON_INTERACTIVE=false

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to get workload directory based on algorithm
get_workloads_dir() {
    local alg="$1"
    
    case "$alg" in
        vanilla)
            echo "${WORKLOADS_BASE_DIR}/workloads-vanilla/"
            ;;
        heuristic|global-optimal)
            echo "${WORKLOADS_BASE_DIR}/workloads/"
            ;;
        *)
            print_error "Invalid algorithm: $alg. Must be one of: vanilla, heuristic, global-optimal"
            exit 1
            ;;
    esac
}

# Function to run the appropriate workload script based on algorithm
run_workload_script() {
    local algorithm="$1"
    local output_dir="$2"
    local experiment_dir
    if [ "$algorithm" = "vanilla" ]; then
        experiment_dir="${output_dir}/${EXPERIMENT_NAME}"
    else
        experiment_dir="${output_dir}/${EXPERIMENT_NAME}_${algorithm}"
    fi
    local log_file="${experiment_dir}/performance.log"
    
    print_message "Running with algorithm: $algorithm"
    print_message "Logging performance metrics to: $log_file"
    print_message "Call interval: $CALL_INTERVAL simulation seconds"
    
    # Make sure the directory exists
    mkdir -p "$(dirname "$log_file")"
    
    # Run the workload script and capture its output
    if [ "$CAPTURE_PERF_METRICS" = true ]; then
        "$(dirname "$0")/applyWorkloadAll.sh" --algorithm "$algorithm" "$SHRINK_FACTOR" "$CALL_INTERVAL" 2>&1 | tee -a "$log_file"
    else
        "$(dirname "$0")/applyWorkloadAll.sh" --algorithm "$algorithm" "$SHRINK_FACTOR" "$CALL_INTERVAL"
    fi
}

# Function to analyze performance metrics from log file
analyze_perf_metrics() {
    local experiment_dir="$1"
    local log_file="${experiment_dir}/performance.log"
    # Set output directory for the analyzer script to raw_data
    local analyzer_output_dir="${experiment_dir}/raw_data"
    # Define the target directory for plots
    local plots_target_dir="${experiment_dir}/plots/performance"
    
    if [ ! -f "$log_file" ]; then
        print_warning "Performance log file not found: $log_file"
        return 1
    fi
    
    print_message "Analyzing performance metrics from $log_file"
    # Ensure the raw_data directory exists
    mkdir -p "$analyzer_output_dir"
    # Call analyzer, outputting CSV and plots to raw_data
    python3 "$(dirname "$0")/perf_metrics_analyzer.py" \
        --log-file "$log_file" \
        --output-dir "$analyzer_output_dir" \
        --output-csv "performance_metrics.csv"
        
    # Now, move the generated plots from raw_data to plots/performance
    if ls "${analyzer_output_dir}"/*.png > /dev/null 2>&1; then
        print_message "Moving performance plots to $plots_target_dir"
        # Ensure the target plot directory exists
        mkdir -p "$plots_target_dir"
        # Move the PNG files
        mv -f "${analyzer_output_dir}"/*.png "$plots_target_dir/"
    else
        print_warning "No performance plots (*.png) found in $analyzer_output_dir to move."
    fi
    
    print_message "Performance CSV saved to $analyzer_output_dir"
    print_message "Performance plots moved to $plots_target_dir"
}

print_header() {
    echo -e "${BLUE}==============================================${NC}"
    echo -e "${BLUE}   Carbon-Aware Scheduler Benchmarking Tool${NC}"
    echo -e "${BLUE}==============================================${NC}"
}

print_message() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

print_error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
}

usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  -n, --name NAME          Experiment name (default: YYYYMMDD_HHMMSS_algorithm)"
    echo "  -i, --interval SECONDS   Metrics collection interval in seconds (default: 60)"
    echo "  -o, --output DIR         Output directory (default: /root/carbon/benchmark_results)"
    echo "  -s, --namespace NAME     Kubernetes namespace to monitor (default: default)"
    echo "  -f, --shrink-factor N    Time shrink factor for simulation time (default: 1)"
    echo "  -a, --algorithm TYPE     Algorithm type: vanilla, heuristic, or global-optimal (default: heuristic)"
    echo "  -c, --compare            Run comparison between carbon and default scheduler"
    echo "  -F, --forecast FILE      Path to carbon intensity forecast file"
    echo "  -h, --help               Display this help message"
    echo "  --call-interval SECONDS  Interval between workload submissions in simulation seconds (default: 3600)"
    echo "  --auto-stop              Non-interactive: stop metrics collector automatically after workload applies"
    echo "  --non-interactive        Non-interactive: auto-confirm prompts (e.g., KWOK settings)"
    exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        -n|--name)
            EXPERIMENT_NAME="$2"
            shift 2
            ;;
        -i|--interval)
            COLLECTION_INTERVAL="$2"
            shift 2
            ;;
        -o|--output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        -s|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -f|--shrink-factor)
            SHRINK_FACTOR="$2"
            shift 2
            ;;
        -a|--algorithm)
            ALGORITHM="$2"
            shift 2
            ;;
        -c|--compare)
            COMPARISON_MODE=true
            shift
            ;;
        -F|--forecast)
            FORECAST_FILE="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        -d|--duration)
            # Keep this option for backward compatibility but we'll ignore its value
            shift 2
            ;;
        --call-interval)
            CALL_INTERVAL="$2"
            shift 2
            ;;
        --auto-stop)
            AUTO_STOP=true
            shift
            ;;
        --non-interactive)
            NON_INTERACTIVE=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            usage
            ;;
    esac
done

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    print_error "Python 3 is required but not installed. Please install Python 3."
    exit 1
fi

# Check if required Python packages are installed
print_message "Checking required Python packages..."
REQUIRED_PACKAGES=("matplotlib" "numpy")
MISSING_PACKAGES=()

for package in "${REQUIRED_PACKAGES[@]}"; do
    if ! python3 -c "import $package" &> /dev/null; then
        MISSING_PACKAGES+=("$package")
    fi
done

if [[ ${#MISSING_PACKAGES[@]} -gt 0 ]]; then
    print_warning "The following Python packages are missing and recommended for full functionality:"
    for package in "${MISSING_PACKAGES[@]}"; do
        echo "  - $package"
    done
    echo
    echo "You can install them with: pip install ${MISSING_PACKAGES[*]}"
    echo "Continuing without these packages may limit some functionality..."
    read -p "Continue anyway? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check if kubectl is configured correctly
if ! kubectl get nodes &> /dev/null; then
    print_error "kubectl cannot connect to the cluster. Please check your Kubernetes configuration."
    exit 1
fi

# Make sure scripts are executable
chmod +x $(dirname "$0")/perf_metrics_analyzer.py

if $COMPARISON_MODE; then
    # Run comparison between carbon and default scheduler
    print_header
    print_message "Starting comparison experiment between carbon and default scheduler"
    print_message "Experiment name: ${EXPERIMENT_NAME}"
    print_message "Collection interval: ${COLLECTION_INTERVAL} seconds"
    print_message "Output directory: ${OUTPUT_DIR}"
    
    # First run with default scheduler
    print_message "Phase 1: Running benchmark with default scheduler..."
    
    # Set up output directory for this run
    DEFAULT_DIR="${OUTPUT_DIR}/${EXPERIMENT_NAME}_default"
    mkdir -p "$DEFAULT_DIR"
    
    # Start capturing performance metrics
    if [ "$CAPTURE_PERF_METRICS" = true ]; then
        print_message "Capturing performance metrics to ${DEFAULT_DIR}/performance.log"
        
        # Run the metrics collection and capture performance logs
        python3 $(dirname "$0")/collect_metrics.py \
            --experiment-name "${EXPERIMENT_NAME}_default" \
            --interval "$COLLECTION_INTERVAL" \
            --namespace "$NAMESPACE" \
            --output-dir "$OUTPUT_DIR" \
            --shrink-factor "$SHRINK_FACTOR" \
            --forecast-file "$FORECAST_FILE" 2>&1 | tee -a "${DEFAULT_DIR}/performance.log"
    else
        # Run without capturing metrics
        python3 $(dirname "$0")/collect_metrics.py \
            --experiment-name "${EXPERIMENT_NAME}_default" \
            --interval "$COLLECTION_INTERVAL" \
            --namespace "$NAMESPACE" \
            --output-dir "$OUTPUT_DIR" \
            --shrink-factor "$SHRINK_FACTOR" \
            --forecast-file "$FORECAST_FILE"
    fi
    
    print_message "Default scheduler benchmark completed"
    
    # Ask the user to switch to the carbon scheduler and prepare the environment
    echo
    print_message "Please prepare your environment for the carbon-aware scheduler:"
    echo "1. Apply your carbon node annotations if needed"
    echo "2. Ensure the carbon-aware scheduler is running"
    echo "3. Clear previous workloads if necessary"
    echo
    read -p "When ready to continue with carbon scheduler benchmark, press Enter..." -r
    
    # Run with carbon-aware scheduler
    print_message "Phase 2: Running benchmark with carbon-aware scheduler..."
    
    # Set up output directory for carbon scheduler run
    CARBON_DIR="${OUTPUT_DIR}/${EXPERIMENT_NAME}_carbon"
    mkdir -p "$CARBON_DIR"
    
    if [ "$CAPTURE_PERF_METRICS" = true ]; then
        print_message "Capturing performance metrics to ${CARBON_DIR}/performance.log"
        
        # Run metrics collection and capture performance logs
        python3 $(dirname "$0")/collect_metrics.py \
            --experiment-name "${EXPERIMENT_NAME}_carbon" \
            --interval "$COLLECTION_INTERVAL" \
            --namespace "$NAMESPACE" \
            --output-dir "$OUTPUT_DIR" \
            --shrink-factor "$SHRINK_FACTOR" \
            --forecast-file "$FORECAST_FILE" 2>&1 | tee -a "${CARBON_DIR}/performance.log"
    else
        # Run without capturing metrics
        python3 $(dirname "$0")/collect_metrics.py \
            --experiment-name "${EXPERIMENT_NAME}_carbon" \
            --interval "$COLLECTION_INTERVAL" \
            --namespace "$NAMESPACE" \
            --output-dir "$OUTPUT_DIR" \
            --shrink-factor "$SHRINK_FACTOR" \
            --forecast-file "$FORECAST_FILE"
    fi
    
    print_message "Carbon scheduler benchmark completed"
    
    # Generate comparison report if both runs were successful
    if [[ -d "${OUTPUT_DIR}/${EXPERIMENT_NAME}_default" && -d "${OUTPUT_DIR}/${EXPERIMENT_NAME}_carbon" ]]; then
        print_message "Generating comparison report..."
        
        # Analyze performance metrics if enabled
        if [ "$CAPTURE_PERF_METRICS" = true ]; then
            print_message "Analyzing performance metrics..."
            analyze_perf_metrics "${DEFAULT_DIR}"
            analyze_perf_metrics "${CARBON_DIR}"
        fi
        
        # Generate metrics analysis
        print_message "Analyzing metrics data..."
        python3 $(dirname "$0")/analyze_metrics.py --data-dir "${DEFAULT_DIR}"
        python3 $(dirname "$0")/analyze_metrics.py --data-dir "${CARBON_DIR}"
        
        print_message "Results saved to:"
        echo "  - ${DEFAULT_DIR}"
        echo "  - ${CARBON_DIR}"
        print_message "To compare results, review the metrics data in these directories"
    else
        print_warning "One or both benchmark runs did not complete successfully."
        print_warning "Check the log files for more information."
    fi
    
else
    # Run a single benchmark
    print_header
    print_message "Starting carbon scheduler benchmark"
    print_message "Experiment name: ${EXPERIMENT_NAME}"
    print_message "Collection interval: ${COLLECTION_INTERVAL} seconds"
    print_message "Shrink factor: ${SHRINK_FACTOR} (simulation time = real time × ${SHRINK_FACTOR})"
    print_message "Output directory: ${OUTPUT_DIR}"
    
    # Automatically update KWOK timing settings to match the shrink factor
    # This ensures pod durations are correctly scaled
    DEFAULT_SHRINK_FACTOR=60
    if [ "$SHRINK_FACTOR" != "$DEFAULT_SHRINK_FACTOR" ]; then
        print_message "Detected non-default shrink factor. Updating KWOK timing settings..."
        if [ "$NON_INTERACTIVE" = true ]; then
            "$(dirname "$0")/apply_kwok_settings.sh" --shrink-factor "$SHRINK_FACTOR" --no-restart || {
                print_error "Failed to update KWOK settings. Exiting."
                exit 1
            }
        else
            # Check if user wants to update KWOK settings
            read -p "Update KWOK timing settings for shrink factor ${SHRINK_FACTOR}? [Y/n] " -n 1 -r UPDATE_KWOK
            echo # Move to a new line
            if [[ $UPDATE_KWOK =~ ^[Yy]$ ]] || [[ -z $UPDATE_KWOK ]]; then
                "$(dirname "$0")/apply_kwok_settings.sh" --shrink-factor "$SHRINK_FACTOR" || {
                    print_error "Failed to update KWOK settings. Exiting."
                    exit 1
                }
            else
                print_warning "KWOK timing settings not updated. Pod durations may not match simulation time."
                print_warning "To update manually, run: $(dirname "$0")/apply_kwok_settings.sh --shrink-factor $SHRINK_FACTOR"
            fi
        fi
    fi
    
    # Set up experiment directory
    if [ "$ALGORITHM" = "vanilla" ]; then
        EXPERIMENT_DIR="${OUTPUT_DIR}/${EXPERIMENT_NAME}"
    else
        EXPERIMENT_DIR="${OUTPUT_DIR}/${EXPERIMENT_NAME}_${ALGORITHM}"
    fi
    mkdir -p "$EXPERIMENT_DIR"
    
    # Start metrics collection in the background
    print_message "Phase 1: Starting metrics collection in the background..."
    METRICS_LOG_FILE="${EXPERIMENT_DIR}/collection.log" # Define log file for collector
    
    if [ "$CAPTURE_PERF_METRICS" = true ]; then
        print_message "Capturing performance metrics to ${EXPERIMENT_DIR}/performance.log"
        # Start collector in background, tee output to both performance log and its own log
        if [ "$ALGORITHM" = "vanilla" ]; then EXP_NAME_FOR_COLLECTOR="${EXPERIMENT_NAME}"; else EXP_NAME_FOR_COLLECTOR="${EXPERIMENT_NAME}_${ALGORITHM}"; fi
        python3 "$(dirname "$0")/collect_metrics.py" \
            --experiment-name "$EXP_NAME_FOR_COLLECTOR" \
            --interval "$COLLECTION_INTERVAL" \
            --namespace "$NAMESPACE" \
            --output-dir "$OUTPUT_DIR" \
            --shrink-factor "$SHRINK_FACTOR" \
            --forecast-file "$FORECAST_FILE" 2>&1 | tee -a "${EXPERIMENT_DIR}/performance.log" > "$METRICS_LOG_FILE" &
        COLLECTOR_PID=$! # Capture the PID of the background process
    else
        # Start collector in background, log to its own file
        if [ "$ALGORITHM" = "vanilla" ]; then EXP_NAME_FOR_COLLECTOR="${EXPERIMENT_NAME}"; else EXP_NAME_FOR_COLLECTOR="${EXPERIMENT_NAME}_${ALGORITHM}"; fi
        python3 "$(dirname "$0")/collect_metrics.py" \
            --experiment-name "$EXP_NAME_FOR_COLLECTOR" \
            --interval "$COLLECTION_INTERVAL" \
            --namespace "$NAMESPACE" \
            --output-dir "$OUTPUT_DIR" \
            --shrink-factor "$SHRINK_FACTOR" \
            --forecast-file "$FORECAST_FILE" > "$METRICS_LOG_FILE" 2>&1 &
        COLLECTOR_PID=$! # Capture the PID of the background process
    fi
    
    print_message "Metrics collector started in background (PID: $COLLECTOR_PID)"
    
    # Run the workload script (this will run in the foreground)
    print_message "Phase 2: Applying workload..."
    # Default call interval to 3600 simulation seconds if unset or <=0
    if [ -z "${CALL_INTERVAL}" ] || [ "${CALL_INTERVAL}" -le 0 ]; then
        CALL_INTERVAL=3600
    fi
    # Start bind-time watcher and presence watcher for vanilla
    if [ "$ALGORITHM" = "vanilla" ]; then
        BIND_WATCHER_LOG="${EXPERIMENT_DIR}/bind_watcher.log"
        print_message "Starting bind-time watcher (logging to ${BIND_WATCHER_LOG})..."
        python3 /root/carbon-aware-orchestrator/scripts/bind_watcher.py \
            --perf-log "${EXPERIMENT_DIR}/performance.log" \
            --binds-out "${EXPERIMENT_DIR}/pod_binds.ndjson" \
            >"${BIND_WATCHER_LOG}" 2>&1 &
        BIND_WATCHER_PID=$!
        print_message "Bind watcher started in background (PID: ${BIND_WATCHER_PID})"

        PRESENCE_WATCH_LOG="${EXPERIMENT_DIR}/presence_watcher.log"
        print_message "Starting presence watcher (logging to ${PRESENCE_WATCH_LOG})..."
        python3 /root/carbon-aware-orchestrator/scripts/cluster_state_watcher.py \
            --perf-log "${EXPERIMENT_DIR}/performance.log" \
            --presence-out "${EXPERIMENT_DIR}/pod_presence.ndjson" \
            --interval 0.5 \
            >"${PRESENCE_WATCH_LOG}" 2>&1 &
        PRESENCE_WATCHER_PID=$!
        print_message "Presence watcher started in background (PID: ${PRESENCE_WATCHER_PID})"
    fi
    run_workload_script "$ALGORITHM" "$OUTPUT_DIR"
    WORKLOAD_EXIT_CODE=$? # Capture exit code of workload script
    
    print_message "Workload application finished."
    # Stop watchers if running
    if [ "$ALGORITHM" = "vanilla" ]; then
        if [ -n "${BIND_WATCHER_PID:-}" ]; then
            print_message "Stopping bind-time watcher (PID: ${BIND_WATCHER_PID})"
            kill "${BIND_WATCHER_PID}" 2>/dev/null || true
        fi
        if [ -n "${PRESENCE_WATCHER_PID:-}" ]; then
            print_message "Stopping presence watcher (PID: ${PRESENCE_WATCHER_PID})"
            kill "${PRESENCE_WATCHER_PID}" 2>/dev/null || true
        fi
    fi

    if [ "$AUTO_STOP" = true ]; then
        print_message "Auto-stop enabled; stopping metrics collector and proceeding to analysis..."
        kill "$COLLECTOR_PID" 2>/dev/null || true
    else
        # Instead of automatically terminating the collector, inform user to press Ctrl+C when ready
        print_message "Metrics collector is still running in the background and collecting data."
        print_message "Press Ctrl+C when you want to stop collection and save the results."
        # Wait for the collector process to finish (will happen when user presses Ctrl+C)
        wait $COLLECTOR_PID
    fi
    
    print_message "Metrics collection stopped. Processing results..."

    # Check if workload script failed
    if [ $WORKLOAD_EXIT_CODE -ne 0 ]; then
        print_error "Workload script failed with exit code $WORKLOAD_EXIT_CODE. Aborting analysis."
        exit $WORKLOAD_EXIT_CODE
    fi
        
    # Then analyze the metrics and generate plots
    print_message "Phase 3: Analyzing metrics and generating plots..."
    python3 $(dirname "$0")/analyze_metrics.py --data-dir "${EXPERIMENT_DIR}"
    
    # Analyze performance metrics if enabled
    if [ "$CAPTURE_PERF_METRICS" = true ]; then
        print_message "Phase 4: Analyzing performance metrics..."
        analyze_perf_metrics "${EXPERIMENT_DIR}"
    fi
    
    # Generate bind-based and presence-based placement CSVs for vanilla by default
    if [ "$ALGORITHM" = "vanilla" ]; then
        print_message "Generating bind-based placement CSV from Scheduled events..."
        VANILLA_WL_DIR="${WORKLOADS_BASE_DIR}/workloads-vanilla/"
        python3 /root/carbon-aware-orchestrator/scripts/generate_bind_based_csv.py \
            --binds-ndjson "${EXPERIMENT_DIR}/pod_binds.ndjson" \
            --workloads-dir "${VANILLA_WL_DIR}" \
            --experiment-dir "${EXPERIMENT_DIR}" || true
        if [ -f "${EXPERIMENT_DIR}/vanilla_placement_session.csv" ]; then
            LINES=$(wc -l < "${EXPERIMENT_DIR}/vanilla_placement_session.csv" || echo 0)
            print_message "Bind-based placement CSV ready: ${EXPERIMENT_DIR}/vanilla_placement_session.csv (rows: $((LINES-1)))"
        else
            print_warning "Bind-based placement CSV was not generated. Check ${EXPERIMENT_DIR}/bind_watcher.log"
        fi

        print_message "Generating presence-based placement CSV from polled cluster state..."
        python3 /root/carbon-aware-orchestrator/scripts/generate_presence_based_csv.py \
            --presence-ndjson "${EXPERIMENT_DIR}/pod_presence.ndjson" \
            --workloads-dir "${VANILLA_WL_DIR}" \
            --experiment-dir "${EXPERIMENT_DIR}" || true
        if [ -f "${EXPERIMENT_DIR}/vanilla_placement_session_presence.csv" ]; then
            LINES=$(wc -l < "${EXPERIMENT_DIR}/vanilla_placement_session_presence.csv" || echo 0)
            print_message "Presence-based placement CSV ready: ${EXPERIMENT_DIR}/vanilla_placement_session_presence.csv (rows: $((LINES-1)))"
        else
            print_warning "Presence-based placement CSV was not generated. Check ${EXPERIMENT_DIR}/presence_watcher.log"
        fi
    fi
    print_message "Benchmark completed"
    print_message "Results saved to: ${EXPERIMENT_DIR}"
    
    # Print summary of key metrics
    if [ -f "${EXPERIMENT_DIR}/results.json" ]; then
        print_message "Key metrics summary:"
        jq -r '.summary.carbon_metrics.total_carbon_emissions_g' "${EXPERIMENT_DIR}/results.json" > /dev/null 2>&1 && \
            echo "  - Total Carbon Emissions: $(jq -r '.summary.carbon_metrics.total_carbon_emissions_g' "${EXPERIMENT_DIR}/results.json") g CO₂"
        jq -r '.summary.performance_metrics.avg_scheduling_latency_seconds' "${EXPERIMENT_DIR}/results.json" > /dev/null 2>&1 && \
            echo "  - Avg Scheduling Latency: $(jq -r '.summary.performance_metrics.avg_scheduling_latency_seconds' "${EXPERIMENT_DIR}/results.json") seconds"
        
        if [ "$CAPTURE_PERF_METRICS" = true ] && [ -f "${EXPERIMENT_DIR}/raw_data/performance_metrics.csv" ]; then
            print_message "Performance metrics summary available at: ${EXPERIMENT_DIR}/raw_data/performance_metrics.csv"
        fi
    fi
fi