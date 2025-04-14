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
EXPERIMENT_NAME="carbon_benchmark_$(date +%Y%m%d_%H%M%S)"
COLLECTION_INTERVAL=60    # Collect metrics every X seconds
NAMESPACE="default"       # Default namespace to monitor
OUTPUT_DIR="/root/carbon/benchmark_results"
COMPARISON_MODE=false     # Whether to run a comparison between schedulers
SHRINK_FACTOR=1          # Default shrink factor is 1 (no time shrinking)
FORECAST_FILE="/root/carbon-aware-orchestrator/pkg/carbon-aware/server-python/all_forecasts.json"
# Removing the fixed EXPERIMENT_DURATION since we'll calculate it dynamically

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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
    echo "  -n, --name NAME          Experiment name (default: carbon_benchmark_TIMESTAMP)"
    echo "  -i, --interval SECONDS   Metrics collection interval in seconds (default: 60)"
    echo "  -o, --output DIR         Output directory (default: /root/carbon/benchmark_results)"
    echo "  -s, --namespace NAME     Kubernetes namespace to monitor (default: default)"
    echo "  -f, --shrink-factor N    Time shrink factor for simulation time (default: 1)"
    echo "  -c, --compare            Run comparison between carbon and default scheduler"
    echo "  -F, --forecast FILE      Path to carbon intensity forecast file"
    echo "  -h, --help               Display this help message"
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

# Make the benchmark script executable
chmod +x $(dirname "$0")/benchmark_metrics.py

if $COMPARISON_MODE; then
    # Run comparison between carbon and default scheduler
    print_header
    print_message "Starting comparison experiment between carbon and default scheduler"
    print_message "Experiment name: ${EXPERIMENT_NAME}"
    print_message "Collection interval: ${COLLECTION_INTERVAL} seconds"
    print_message "Output directory: ${OUTPUT_DIR}"
    
    # First run with default scheduler
    print_message "Phase 1: Running benchmark with default scheduler..."
    python3 $(dirname "$0")/collect_metrics.py \
        --name "${EXPERIMENT_NAME}_default" \
        --interval "$COLLECTION_INTERVAL" \
        --namespace "$NAMESPACE" \
        --output-dir "$OUTPUT_DIR" \
        --shrink-factor "$SHRINK_FACTOR" \
        --forecast-file "$FORECAST_FILE"
    
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
    python3 $(dirname "$0")/collect_metrics.py \
        --name "${EXPERIMENT_NAME}_carbon" \
        --interval "$COLLECTION_INTERVAL" \
        --namespace "$NAMESPACE" \
        --output-dir "$OUTPUT_DIR" \
        --shrink-factor "$SHRINK_FACTOR" \
        --forecast-file "$FORECAST_FILE"
    
    print_message "Carbon scheduler benchmark completed"
    
    # Generate comparison report if both runs were successful
    if [[ -d "${OUTPUT_DIR}/${EXPERIMENT_NAME}_default" && -d "${OUTPUT_DIR}/${EXPERIMENT_NAME}_carbon" ]]; then
        print_message "Generating comparison report..."
        # In a future enhancement, add code here to generate a comparison report
        # between the carbon and default scheduler results
        
        print_message "Results saved to:"
        echo "  - ${OUTPUT_DIR}/${EXPERIMENT_NAME}_default"
        echo "  - ${OUTPUT_DIR}/${EXPERIMENT_NAME}_carbon"
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
    
    # First collect the metrics - without a fixed duration
    print_message "Phase 1: Collecting metrics data..."
    python3 $(dirname "$0")/collect_metrics.py \
        --name "$EXPERIMENT_NAME" \
        --interval "$COLLECTION_INTERVAL" \
        --namespace "$NAMESPACE" \
        --output-dir "$OUTPUT_DIR" \
        --shrink-factor "$SHRINK_FACTOR" \
        --forecast-file "$FORECAST_FILE"
        
    # Then analyze the metrics and generate plots
    print_message "Phase 2: Analyzing metrics and generating plots..."
    python3 $(dirname "$0")/analyze_metrics.py \
        --data-dir "${OUTPUT_DIR}/${EXPERIMENT_NAME}"
    
    print_message "Benchmark completed"
    print_message "Results saved to: ${OUTPUT_DIR}/${EXPERIMENT_NAME}"
fi

# Final message with instructions for analyzing results
echo
print_message "Analysis instructions:"
echo "1. Review the summary in results.json"
echo "2. Examine the time series data in the raw_data directory"
echo "3. Check the generated plots in the plots directory (if matplotlib was available)"
echo
print_message "For quick insights run:"
echo "  cat ${OUTPUT_DIR}/${EXPERIMENT_NAME}/results.json | jq"