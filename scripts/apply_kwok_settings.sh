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

# Default values
DEFAULT_SHRINK_FACTOR=60
CARBON_ROOT="/root/carbon"
KWOK_CONFIG_FILE="${CARBON_ROOT}/k8s/kwok-config.yaml"
UPDATE_SCRIPT="${CARBON_ROOT}/scripts/update_kwok_durations.sh"

# Function to display usage information
usage() {
    echo "Usage: $0 [options]"
    echo "Options:"
    echo "  -s, --shrink-factor VALUE    Shrink factor to use (default: $DEFAULT_SHRINK_FACTOR)"
    echo "  -n, --no-restart             Update configuration only, don't restart KWOK"
    echo "  -h, --help                   Display this help message and exit"
    echo ""
    echo "This script updates pod durations and other timing settings in the KWOK config"
    echo "file based on the shrink factor, then restarts KWOK to apply the changes."
    echo "Example: $0 --shrink-factor 120"
    exit 1
}

# Parse command line arguments
SHRINK_FACTOR=$DEFAULT_SHRINK_FACTOR
RESTART_KWOK=true

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
        -n|--no-restart)
            RESTART_KWOK=false
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

# Step 1: Update KWOK durations
echo "==== Step 1: Updating KWOK timing settings for shrink factor $SHRINK_FACTOR ===="
$UPDATE_SCRIPT --shrink-factor "$SHRINK_FACTOR" --backup

# Exit if user requested only the update
if ! $RESTART_KWOK; then
    echo "Configuration updated but KWOK was not restarted as requested (--no-restart)."
    echo "To apply changes later, run: make -C $CARBON_ROOT kwok"
    exit 0
fi

# Step 2: Restart the KWOK cluster
echo "==== Step 2: Recreating KWOK cluster to apply new settings ===="
echo "This will recreate the KWOK cluster with the new timing settings."
echo "WARNING: This will delete and recreate all simulated nodes and stages."

# Prompt for confirmation before proceeding
read -p "Continue with KWOK restart? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Restart aborted. Configuration has been updated but not applied."
    echo "To apply changes later, run: make -C $CARBON_ROOT kwok"
    exit 0
fi

# Run the kwok target from the Makefile
echo "Recreating KWOK cluster..."
make -C "$CARBON_ROOT" kwok

echo "==== Completed: KWOK has been updated and restarted ===="
echo "The new timing settings are now active with shrink factor: $SHRINK_FACTOR"
echo "Pod durations have been adjusted to maintain consistent simulation time."
