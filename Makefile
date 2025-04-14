#
# Copyright 2024 Fondazione Bruno Kessler.
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

build:                  
	CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o ./bin/kubectl-carbon main.go

kwok:
# Delete old cluster (if any)
	-kwokctl delete cluster --name carbon
# Pull the custom scheduler image
	docker pull gitlab-registry.fbk.eu/fogatlas-k8s/scheduler-plugins/kube-scheduler:v0.28.8.3
# Create the cluster
	kwokctl -c ./k8s/kwok-config.yaml create cluster --name carbon
# Create the nodes
	kubectl apply -f /root/carbon-aware-orchestrator/pkg/carbon-aware/nodes.yaml	
# Install CRDs
	kubectl apply -f ./k8s/fogatlas.fbk.eu_faplacements.yaml
# Deploy unschedulable pod (needed by the custom scheduler but it doesn't affect the experiment)	
	sleep 5; kubectl apply -f k8s/unschedulable.yaml

