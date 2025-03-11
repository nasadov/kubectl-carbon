/*
 *Copyright 2025 Fondazione Bruno Kessler.
 *
 *Licensed under the Apache License, Version 2.0 (the "License");
 *you may not use this file except in compliance with the License.
 *You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 *Unless required by applicable law or agreed to in writing, software
 *distributed under the License is distributed on an "AS IS" BASIS,
 *WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *See the License for the specific language governing permissions and
 *limitations under the License.
 *
 */

package cmd

import (
	"context"
	"os"
	"strings"

	algorithm "gitlab.fbk.eu/fogatlas-k8s/algorithms/pkg/generated-go/idl"
	v1 "k8s.io/api/apps/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/client-go/kubernetes"
	"sigs.k8s.io/yaml"
)

// LoadWorkloadFromFile function
func LoadWorkloadFromFile(deplfile string, workload *algorithm.Workload) (err error) {
	// Load from file
	yamlFile, err := os.ReadFile(deplfile)
	if err != nil {
		return err
	}

	// Split deployments
	depls := strings.Split(string(yamlFile), "---")
	for _, depl := range depls {
		if strings.TrimSpace(depl) == "" {
			continue // skip empty documents
		}

		// Unmarshal the YAML into a Kubernetes Deployment struct
		var deployment v1.Deployment
		err = yaml.Unmarshal([]byte(depl), &deployment)
		if err != nil {
			return err
		}
		microservice := new(algorithm.Microservice)
		microservice.Name = deployment.Name
		microservice.DurationHours = deployment.Labels["duration"]
		microservice.DeadlineHours = deployment.Labels["deadline"]
		microservice.Replicas = *deployment.Spec.Replicas
		microservice.CpuRequired = &algorithm.ResourceQuantity{
			Value:  deployment.Spec.Template.Spec.Containers[0].Resources.Requests.Cpu().String(),
			Format: string(deployment.Spec.Template.Spec.Containers[0].Resources.Requests.Cpu().Format),
		}
		microservice.MemRequired = &algorithm.ResourceQuantity{
			Value:  deployment.Spec.Template.Spec.Containers[0].Resources.Requests.Memory().String(),
			Format: string(deployment.Spec.Template.Spec.Containers[0].Resources.Requests.Memory().Format),
		}
		microservice.Status = algorithm.MicroserviceStatus_TO_DEPLOY
		workload.Microservices = append(workload.Microservices, microservice)

	}

	return nil
}

// LoadWorkloadFromCluster function
func LoadWorkloadFromCluster(kubeclientset kubernetes.Interface, namespace string, workload *algorithm.Workload) (err error) {
	// Load from cluster
	depls, err := kubeclientset.AppsV1().Deployments(namespace).List(context.TODO(), metav1.ListOptions{})
	if err != nil {
		return err
	}

	for _, ms := range depls.Items {
		microservice := new(algorithm.Microservice)
		microservice.Name = ms.Name
		microservice.Replicas = *ms.Spec.Replicas
		microservice.DurationHours = ms.Labels["duration"]
		microservice.DeadlineHours = ms.Labels["deadline"]
		microservice.CpuRequired = &algorithm.ResourceQuantity{
			Value:  ms.Spec.Template.Spec.Containers[0].Resources.Requests.Cpu().String(),
			Format: string(ms.Spec.Template.Spec.Containers[0].Resources.Requests.Cpu().Format),
		}
		microservice.MemRequired = &algorithm.ResourceQuantity{
			Value:  ms.Spec.Template.Spec.Containers[0].Resources.Requests.Memory().String(),
			Format: string(ms.Spec.Template.Spec.Containers[0].Resources.Requests.Memory().Format),
		}
		// Get the nodes selected for each pod of this microservice (should be one since we are using a single replica)
		selectors := ms.Spec.Selector.MatchLabels
		set := labels.Set(selectors)
		pods, err := kubeclientset.CoreV1().Pods("").List(context.TODO(), metav1.ListOptions{LabelSelector: set.AsSelector().String()})
		if err != nil {
			return err
		}
		if len(pods.Items) > 0 {
			for _, p := range pods.Items {
				deployedon := p.Spec.NodeName
				microservice.DeployedOn = append(microservice.DeployedOn, deployedon)
				// assume just one replica
				if p.Status.Phase == "Running" {
					microservice.Status = algorithm.MicroserviceStatus_RUNNING
				} else {
					microservice.Status = algorithm.MicroserviceStatus_PENDING
				}
			}
		}
		workload.Microservices = append(workload.Microservices, microservice)
	}
	return nil
}

// LoadWorkload function
func LoadWorkload(kubeclientset kubernetes.Interface, namespace string, deplfile string) (workload *algorithm.Workload, err error) {
	workload = new(algorithm.Workload)

	// Load from file
	err = LoadWorkloadFromFile(deplfile, workload)
	if err != nil {
		return nil, err
	}

	// Load from cluster
	err = LoadWorkloadFromCluster(kubeclientset, namespace, workload)
	if err != nil {
		return nil, err
	}

	return workload, nil
}
