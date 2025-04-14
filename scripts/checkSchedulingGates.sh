#!/usr/bin/env bash

#
# Copyright 2025 Fondazione Bruno Kessler and Carbon Contributors.
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

#
# If scheduling time has arrived drop scheduling gate
#

# Retrieve pods list (currently all pods in the default namespace)
pods=($(kubectl get pods |grep SchedulingGated |awk '{print $1}'))

# For each pod check if it is time to schedule, drop the scheduling gate
for pod in ${pods[@]}; do
    echo "Checking schedulability of pods $pod"
    time_to_schedule=$(kubectl get pod $pod -o jsonpath='{.metadata.labels.timeToSchedule}')
    current_time=$(date +%s)
    if [ "$time_to_schedule" -lt "$current_time" ]
    then
        echo "Going to remove scheduling gate"
        kubectl patch pod $pod --type=json -p='[{"op": "replace", "path": "/spec/schedulingGates", "value": []}]'
    else
        echo "Still to wait $((time_to_schedule-current_time)) seconds"
    fi
done

echo "No more pods to check"