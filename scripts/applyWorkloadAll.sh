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

# Parse command line arguments
usage() {
    echo "Usage: $0 [shrink_factor] [call_interval]"
    echo "  shrink_factor: Value for -w flag (default: 60, simulates 60 simulation seconds per real second)"
    echo "  call_interval: Simulation seconds between file submissions (default: 3600, simulates 1 hour)"
    exit 1
}

# Check if arguments were provided
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

if [ $# -gt 2 ]; then
    echo "Warning: Ignoring additional parameters"
fi

WORKLOADS_DIR="/root/carbon-aware-orchestrator/pkg/carbon-aware/workloads/"

echo "Starting carbon-aware scheduler with sequential timeslot processing"
echo "Shrink factor: ${SHRINK_FACTOR} (1 real second = ${SHRINK_FACTOR} simulation seconds)"
echo "Call interval: ${CALL_INTERVAL} simulation seconds (equivalent to $(echo "scale=2; ${CALL_INTERVAL}/${SHRINK_FACTOR}" | bc) real seconds)"

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
    
    # Submit the current file with the shrink factor
    kubectl carbon -f "$yaml_file" -w "$SHRINK_FACTOR"
    
    echo "---"
    
    # If this isn't the last file, wait before processing the next one
    if [ $i -lt $((total_files-1)) ]; then
        echo "Waiting ${CALL_INTERVAL} simulation seconds (${REAL_SLEEP_TIME} real seconds) before processing next timeslot..."
        sleep $REAL_SLEEP_TIME
    fi
done

echo "===== $(date): All timeslots processed ====="
echo "Experiment completed successfully"