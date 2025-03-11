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

## License

Copyright 2025 Fondazione Bruno Kessler

Licensed under the Apache License, Version 2.0 (the “License”); you may not use this
file except in compliance with the License. You may obtain a copy of the License
[here](http://www.apache.org/licenses/LICENSE-2.0).

Unless required by applicable law or agreed to in writing, software distributed under
the License is distributed on an “AS IS” BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
either express or implied. See the License for the specific language governing permissions
and limitations under the License.


