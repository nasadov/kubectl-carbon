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
CALL_INTERVAL=1        # Time between processing files (in seconds)
SHRINK_FACTOR=3600     # Shrink factor for kubectl carbon (-w flag)

# Parse command line arguments
usage() {
    echo "Usage: $0 [call_interval_seconds] [shrink_factor]"
    echo "  call_interval_seconds: Time to wait between files (default: 1)"
    echo "  shrink_factor: Value for -w flag (default: 3600, simulates 1 hour per second)"
    exit 1
}

# Check if arguments were provided
if [ $# -ge 1 ]; then
    if [[ "$1" =~ ^[0-9]+$ ]]; then
        CALL_INTERVAL=$1
    else
        echo "Error: Call interval must be a positive integer"
        usage
    fi
fi

if [ $# -ge 2 ]; then
    if [[ "$2" =~ ^[0-9]+$ ]]; then
        SHRINK_FACTOR=$2
    else
        echo "Error: Shrink factor must be a positive integer"
        usage
    fi
fi

if [ $# -gt 2 ]; then
    echo "Warning: Ignoring additional parameters"
fi

WORKLOADS_DIR="/root/carbon-aware-orchestrator/pkg/carbon-aware/workloads/"

echo "Starting carbon-aware scheduler"
echo "Call interval: ${CALL_INTERVAL}s"
echo "Shrink factor: ${SHRINK_FACTOR} (1 second = ${SHRINK_FACTOR} simulation seconds)"

# Get initial sorted list of files
if [ ! -d "$WORKLOADS_DIR" ]; then
    echo "Error: Directory not found: $WORKLOADS_DIR"
    exit 1
fi

# Get and sort files outside the main loop
mapfile -t yaml_files < <(find "$WORKLOADS_DIR" -name "*.yaml" -o -name "*.yml" 2>/dev/null | sort -t_ -k2 -n)

# Check if any files were found
if [ ${#yaml_files[@]} -eq 0 ]; then
    echo "Error: No YAML files found in $WORKLOADS_DIR"
    exit 1
fi

total_files=${#yaml_files[@]}
echo "Found $total_files files to process in sequence"

# Process each file once and then exit
for ((i=0; i<total_files; i++)); do
    yaml_file="${yaml_files[$i]}"
    
    echo "===== $(date): Processing file $((i+1))/$total_files ====="
    echo "Processing: $(basename "$yaml_file")"
    
    # Process the current file with the shrink factor
    kubectl carbon -f "$yaml_file" -w "$SHRINK_FACTOR"
    
    echo "---"
    
    # If this isn't the last file, wait before processing the next one
    if [ $i -lt $((total_files-1)) ]; then
        echo "Waiting ${CALL_INTERVAL} seconds before processing next file..."
        sleep $CALL_INTERVAL
    fi
done

echo "===== $(date): All workloads processed ====="
echo "Experiment completed successfully"