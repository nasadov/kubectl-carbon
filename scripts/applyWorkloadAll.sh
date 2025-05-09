#!/bin/bash

# Copyright 2025 Fondazione Bruno Kessler and Carbon Contributors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Default values
CALL_INTERVAL=3600    # Time between processing files (in simulation seconds)
SHRINK_FACTOR=60      # Shrink factor for kubectl carbon (-w flag)
WORKLOADS_BASE_DIR="/root/carbon-aware-orchestrator/pkg/carbon-aware"  # Base directory for workloads
ALGORITHM=""          # Initialize to empty string to force explicit specification

# Parse command line arguments
usage() {
    echo "Usage: $0 [options] [shrink_factor] [call_interval]"
    echo "Options:"
    echo "  --algorithm TYPE        Algorithm type: vanilla, heuristic, or global-optimal (REQUIRED)"
    echo "  --workloads-dir DIR     Custom directory for workloads (overrides algorithm-based directory)"
    echo ""
    echo "Positional arguments:"
    echo "  shrink_factor: Value for -w flag (default: 60, simulates 60 simulation seconds per real second)"
    echo "  call_interval: Simulation seconds between file submissions (default: 3600, simulates 1 hour)"
    echo ""
    echo "Default workload directories:"
    echo "  vanilla:        ${WORKLOADS_BASE_DIR}/workloads-vanilla/"
    echo "  heuristic:      ${WORKLOADS_BASE_DIR}/workloads/"
    echo "  global-optimal: ${WORKLOADS_BASE_DIR}/workloads/"
    exit 1
}

# Parse named arguments first (if any)
while [[ $# -gt 0 ]]; do
    case "$1" in
        --algorithm)
            if [[ "$2" == "vanilla" || "$2" == "heuristic" || "$2" == "global-optimal" ]]; then
                ALGORITHM="$2"
                shift 2
            else
                echo "Error: Invalid algorithm type. Must be one of: vanilla, heuristic, global-optimal"
                usage
            fi
            ;;
        --workloads-dir)
            CUSTOM_WORKLOADS_DIR="$2"
            shift 2
            ;;
        -h|--help)
            usage
            ;;
        *)
            # If it's not a named argument, break out to positional argument handling
            break
            ;;
    esac
done

# Check if algorithm was specified
if [ -z "$ALGORITHM" ]; then
    echo "Error: --algorithm flag is required. Must specify: vanilla, heuristic, or global-optimal"
    usage
fi

# Now handle positional arguments
if [ $# -ge 1 ]; then
    if [[ "$1" =~ ^[0-9]+$ ]]; then
        SHRINK_FACTOR=$1
    else
        echo "Error: Shrink factor must be a positive integer"
        usage
    fi
fi

if [ $# -ge 2 ]; then
    if [[ "$2" =~ ^[0-9]+$ ]]; then
        CALL_INTERVAL=$2
    else
        echo "Error: Call interval must be a positive integer"
        usage
    fi
fi

# Set workloads directory based on algorithm type
if [ -n "$CUSTOM_WORKLOADS_DIR" ]; then
    # Use custom directory if specified
    WORKLOADS_DIR="$CUSTOM_WORKLOADS_DIR"
else
    # Set directory based on algorithm
    if [ "$ALGORITHM" == "vanilla" ]; then
        WORKLOADS_DIR="${WORKLOADS_BASE_DIR}/workloads-vanilla/"
    else
        # Both heuristic and global-optimal use the same workloads directory
        WORKLOADS_DIR="${WORKLOADS_BASE_DIR}/workloads/"
    fi
fi

# Ensure trailing slash for consistency
[[ "${WORKLOADS_DIR}" != */ ]] && WORKLOADS_DIR="${WORKLOADS_DIR}/"

# Determine which kubectl command to use based on algorithm
if [ "$ALGORITHM" == "vanilla" ]; then
    KUBECTL_CMD="kubectl"
    echo "Starting standard Kubernetes scheduler with sequential timeslot processing"
    echo "Algorithm type: ${ALGORITHM} (using standard kubectl)"
else
    KUBECTL_CMD="kubectl carbon"
    echo "Starting carbon-aware scheduler with sequential timeslot processing"
    echo "Algorithm type: ${ALGORITHM} (using kubectl carbon)"
fi

echo "Shrink factor: ${SHRINK_FACTOR} (1 real second = ${SHRINK_FACTOR} simulation seconds)"
echo "Call interval: ${CALL_INTERVAL} simulation seconds (equivalent to $(echo "scale=2; ${CALL_INTERVAL}/${SHRINK_FACTOR}" | bc) real seconds)"
echo "Using workloads from: ${WORKLOADS_DIR}"

# Calculate real sleep time between calls
REAL_SLEEP_TIME=$(echo "scale=2; ${CALL_INTERVAL}/${SHRINK_FACTOR}" | bc)

# Check if directory exists
if [ ! -d "$WORKLOADS_DIR" ]; then
    echo "Error: Directory not found: $WORKLOADS_DIR"
    exit 1
fi

# Get and sort files
mapfile -t yaml_files < <(find "$WORKLOADS_DIR" -name "*.yaml" -o -name "*.yml" 2>/dev/null | sort -t_ -k2 -n)

# Check if any files were found
if [ ${#yaml_files[@]} -eq 0 ]; then
    echo "Error: No YAML files found in $WORKLOADS_DIR"
    exit 1
fi

total_files=${#yaml_files[@]}
echo "Found $total_files files to process in sequence"

# Process each file with the specified interval
for ((i=0; i<total_files; i++)); do
    yaml_file="${yaml_files[$i]}"
    
    echo "===== $(date): Processing timeslot $((i+1))/$total_files ====="
    echo "Processing: $(basename "$yaml_file")"
    
    # Submit the current file with the appropriate command
    if [ "$ALGORITHM" == "vanilla" ]; then
        # For vanilla, use regular kubectl apply
        ${KUBECTL_CMD} apply -f "$yaml_file"
    else
        # For carbon-aware schedulers, use kubectl carbon with shrink factor
        ${KUBECTL_CMD} -f "$yaml_file" -w "$SHRINK_FACTOR"
    fi
    
    echo "---"
    
    # If this isn't the last file, wait before processing the next one
    if [ $i -lt $((total_files-1)) ]; then
        echo "Waiting ${CALL_INTERVAL} simulation seconds (${REAL_SLEEP_TIME} real seconds) before processing next timeslot..."
        sleep $REAL_SLEEP_TIME
    fi
done

echo "===== $(date): All timeslots processed ====="
echo "Entering extended metrics collection phase for 12 more simulation hours..."

# Continue collecting metrics for 12 more simulation hours
for ((hour=1; hour<=12; hour++)); do
    # Sleep for one simulation hour
    sleep $REAL_SLEEP_TIME

    echo "===== $(date): Extended collection - Simulation hour $((total_files + hour)) of $((total_files + 12)) ====="
    echo "No new workloads deployed, continuing metrics collection for running pods..."
done

echo "===== $(date): Extended metrics collection completed ====="
echo "Experiment completed successfully"