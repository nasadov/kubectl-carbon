#!/bin/bash

# Copyright 2025 Technische Universitaet Berlin.
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

# Default configurations
KWOK_CONFIG_FILE="/root/carbon/k8s/kwok-config.yaml"
DEFAULT_SHRINK_FACTOR=60
BACKUP_SUFFIX=".bak"

# Function to display usage information
usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  -s, --shrink-factor VALUE    Shrink factor to use (default: $DEFAULT_SHRINK_FACTOR)"
    echo "  -f, --file PATH              Path to KWOK config file (default: $KWOK_CONFIG_FILE)"
    echo "  -b, --backup                 Create a backup of original file (with $BACKUP_SUFFIX suffix)"
    echo "  -h, --help                   Display this help message and exit"
    echo ""
    echo "This script updates the pod durations in the KWOK config file based on the shrink factor."
    echo "Example: $0 --shrink-factor 120"
    exit 1
}

# Function to calculate duration in milliseconds
calculate_duration_ms() {
    local hours=$1
    local shrink_factor=$2
    
    # Formula: hours * 3600 * 1000 / shrink_factor
    # 3600: seconds per hour
    # 1000: milliseconds per second
    # Example: 1 hour with shrink factor 60 = 3600*1000/60 = 60000ms = 1 minute
    echo $(( hours * 3600 * 1000 / shrink_factor ))
}

# Parse command line arguments
SHRINK_FACTOR=$DEFAULT_SHRINK_FACTOR
CREATE_BACKUP=false

while [[ $# -gt 0 ]]; do
    key="$1"
    case $key in
        -s|--shrink-factor)
            SHRINK_FACTOR="$2"
            if ! [[ $SHRINK_FACTOR =~ ^[0-9]+$ ]]; then
                echo "Error: Shrink factor must be a positive integer"
                exit 1
            fi
            shift 2
            ;;
        -f|--file)
            KWOK_CONFIG_FILE="$2"
            if [ ! -f "$KWOK_CONFIG_FILE" ]; then
                echo "Error: KWOK config file not found: $KWOK_CONFIG_FILE"
                exit 1
            fi
            shift 2
            ;;
        -b|--backup)
            CREATE_BACKUP=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Error: Unknown option: $1"
            usage
            ;;
    esac
done

echo "Updating pod durations in KWOK config for shrink factor: $SHRINK_FACTOR"
echo "Config file: $KWOK_CONFIG_FILE"

# Create backup if requested
if $CREATE_BACKUP; then
    cp "$KWOK_CONFIG_FILE" "${KWOK_CONFIG_FILE}${BACKUP_SUFFIX}"
    echo "Backup created: ${KWOK_CONFIG_FILE}${BACKUP_SUFFIX}"
fi

# Update pod durations (1-12 hours)
echo "--- Updating pod duration stages ---"
for hour in {1..12}; do
    duration_ms=$(calculate_duration_ms $hour $SHRINK_FACTOR)
    
    # Find the stage definition line
    stage_line=$(grep -n "name: delete-pods-${hour}h-stage" "$KWOK_CONFIG_FILE" | cut -d':' -f1)
    
    if [[ -n "$stage_line" ]]; then
        # Find the durationMilliseconds line within 15 lines after the stage definition
        duration_line=$(tail -n +$stage_line "$KWOK_CONFIG_FILE" | grep -n "durationMilliseconds:" | head -1 | cut -d':' -f1)
        
        if [[ -n "$duration_line" ]]; then
            # Calculate absolute line number in file
            actual_line=$((stage_line + duration_line - 1))
            # Update the duration value
            sed -i "${actual_line}s/durationMilliseconds: [0-9]*/durationMilliseconds: $duration_ms/" "$KWOK_CONFIG_FILE"
            echo "Updated duration-${hour}h: $duration_ms ms ($(echo "scale=2; $duration_ms/1000/60" | bc) minutes)"
        else
            echo "Warning: Couldn't find durationMilliseconds line for stage delete-pods-${hour}h-stage"
        fi
    else
        echo "Warning: Couldn't find stage delete-pods-${hour}h-stage"
    fi
done

# Update node heartbeat durations
echo -e "\n--- Updating node heartbeat durations ---"
# Default values: 600000ms (10 minutes)
NODE_HEARTBEAT_MS=600000
NODE_HEARTBEAT_JITTER_MS=610000

# Calculate new values - 10 minutes in simulation time
NEW_HEARTBEAT_MS=$(( 10 * 60 * 1000 / SHRINK_FACTOR ))
NEW_HEARTBEAT_JITTER_MS=$(( NEW_HEARTBEAT_MS + 10000 / SHRINK_FACTOR ))

# Update node heartbeat durations (there are two identical stages)
# Find both instances of the node-heartbeat-with-lease stage
mapfile -t heartbeat_lines < <(grep -n "name: node-heartbeat-with-lease" "$KWOK_CONFIG_FILE" | cut -d':' -f1)

for line in "${heartbeat_lines[@]}"; do
    # Find the durationMilliseconds line
    duration_line=$(tail -n +$line "$KWOK_CONFIG_FILE" | grep -n "durationMilliseconds:" | head -1 | cut -d':' -f1)
    
    if [[ -n "$duration_line" ]]; then
        # Calculate absolute line number in file
        actual_line=$((line + duration_line - 1))
        # Update the duration value
        sed -i "${actual_line}s/durationMilliseconds: [0-9]*/durationMilliseconds: $NEW_HEARTBEAT_MS/" "$KWOK_CONFIG_FILE"
        
        # Find the jitterDurationMilliseconds line (usually right after durationMilliseconds)
        jitter_line=$(tail -n +$actual_line "$KWOK_CONFIG_FILE" | grep -n "jitterDurationMilliseconds:" | head -1 | cut -d':' -f1)
        
        if [[ -n "$jitter_line" ]]; then
            # Calculate absolute line number in file
            actual_jitter_line=$((actual_line + jitter_line - 1))
            # Update the jitter value
            sed -i "${actual_jitter_line}s/jitterDurationMilliseconds: [0-9]*/jitterDurationMilliseconds: $NEW_HEARTBEAT_JITTER_MS/" "$KWOK_CONFIG_FILE"
        fi
    fi
done

echo "Updated node heartbeat duration: $NEW_HEARTBEAT_MS ms ($(echo "scale=2; $NEW_HEARTBEAT_MS/1000/60" | bc) minutes)"
echo "Updated node heartbeat jitter: $NEW_HEARTBEAT_JITTER_MS ms ($(echo "scale=2; $NEW_HEARTBEAT_JITTER_MS/1000/60" | bc) minutes)"

# Update pod deletion delay
echo -e "\n--- Updating pod deletion delay ---"
# Default value: 5000ms (5 seconds)
POD_DELETE_MS=5000
NEW_POD_DELETE_MS=$(( 5 * 1000 / SHRINK_FACTOR ))

# Update pod deletion duration
pod_delete_line=$(grep -n "name: pod-delete" "$KWOK_CONFIG_FILE" | cut -d':' -f1)

if [[ -n "$pod_delete_line" ]]; then
    # Find the durationMilliseconds line within 15 lines after the stage definition
    duration_line=$(tail -n +$pod_delete_line "$KWOK_CONFIG_FILE" | grep -n "durationMilliseconds:" | head -1 | cut -d':' -f1)
    
    if [[ -n "$duration_line" ]]; then
        # Calculate absolute line number in file
        actual_line=$((pod_delete_line + duration_line - 1))
        # Update the duration value
        sed -i "${actual_line}s/durationMilliseconds: [0-9]*/durationMilliseconds: $NEW_POD_DELETE_MS/" "$KWOK_CONFIG_FILE"
    else
        echo "Warning: Couldn't find durationMilliseconds line for pod-delete stage"
    fi
else
    echo "Warning: Couldn't find pod-delete stage"
fi

echo "Updated pod deletion delay: $NEW_POD_DELETE_MS ms ($(echo "scale=2; $NEW_POD_DELETE_MS/1000" | bc) seconds)"

# Update node lease duration seconds
echo -e "\n--- Updating node lease duration ---"
# Default value: 200 seconds
NODE_LEASE_SECONDS=200
NEW_NODE_LEASE_SECONDS=$(( 200 / SHRINK_FACTOR ))
if [ $NEW_NODE_LEASE_SECONDS -lt 10 ]; then
    NEW_NODE_LEASE_SECONDS=10
    echo "Warning: Calculated node lease duration too small, using minimum value of 10 seconds"
fi

# Update node lease duration in both locations
# Update the node-lease-duration-seconds parameter in the command line args
arg_line=$(grep -n -- "--node-lease-duration-seconds=" "$KWOK_CONFIG_FILE" | cut -d':' -f1)
if [[ -n "$arg_line" ]]; then
    sed -i "${arg_line}s/--node-lease-duration-seconds=[0-9]*/--node-lease-duration-seconds=$NEW_NODE_LEASE_SECONDS/" "$KWOK_CONFIG_FILE"
else
    echo "Warning: Couldn't find --node-lease-duration-seconds parameter"
fi

# Update the nodeLeaseDurationSeconds field
lease_line=$(grep -n "nodeLeaseDurationSeconds:" "$KWOK_CONFIG_FILE" | cut -d':' -f1)
if [[ -n "$lease_line" ]]; then
    sed -i "${lease_line}s/nodeLeaseDurationSeconds: [0-9]*/nodeLeaseDurationSeconds: $NEW_NODE_LEASE_SECONDS/" "$KWOK_CONFIG_FILE"
else
    echo "Warning: Couldn't find nodeLeaseDurationSeconds field"
fi

echo "Updated node lease duration: $NEW_NODE_LEASE_SECONDS seconds"

echo "KWOK config file updated successfully!"
echo ""
echo "IMPORTANT: These changes will NOT take effect until the KWOK cluster is recreated!"
echo "To apply these changes, you must restart the KWOK cluster:"
echo ""
echo "  make -C /root/carbon kwok"
echo ""
echo "This will completely recreate the KWOK cluster with the new timing settings."
