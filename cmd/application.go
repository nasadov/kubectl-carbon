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
	"fmt"
	"os"
	"strings"

	algorithm "gitlab.fbk.eu/fogatlas-k8s/algorithms/pkg/generated-go/idl"
	v1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"k8s.io/client-go/kubernetes"
	"sigs.k8s.io/yaml"
)

// getSafeResourceQuantity safely extracts resource quantities, handling nil cases
func getSafeResourceQuantity(container *corev1.Container, resourceName corev1.ResourceName) *algorithm.ResourceQuantity {
	// Always return a valid value that will survive serialization
	var value, format string

	// Default values
	if resourceName == corev1.ResourceCPU {
		value = "100m"
		format = "DecimalSI"
	} else { // Memory
		value = "100Mi"
		format = "BinarySI"
	}

	// Try to get actual values if available
	if container != nil && container.Resources.Requests != nil {
		quantity, exists := container.Resources.Requests[resourceName]
		if exists && !quantity.IsZero() {
			value = quantity.String()
			format = string(quantity.Format)
		}
	}

	// Ensure value is never empty - protobuf might ignore empty strings
	if value == "" {
		if resourceName == corev1.ResourceCPU {
			value = "100m"
		} else {
			value = "100Mi"
		}
	}

	// Ensure format is never empty
	if format == "" {
		if resourceName == corev1.ResourceCPU {
			format = "DecimalSI"
		} else {
			format = "BinarySI"
		}
	}

	return &algorithm.ResourceQuantity{
		Value:  value,
		Format: format,
	}
}

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
		// Safely get CPU and memory requirements
		if len(deployment.Spec.Template.Spec.Containers) > 0 {
			container := &deployment.Spec.Template.Spec.Containers[0]
			microservice.CpuRequired = getSafeResourceQuantity(container, corev1.ResourceCPU)
			microservice.MemRequired = getSafeResourceQuantity(container, corev1.ResourceMemory)
			fmt.Printf("Setting CPU: %s, Memory: %s for %s\n", microservice.CpuRequired.Value, microservice.MemRequired.Value, microservice.Name)
		} else {
			microservice.CpuRequired = &algorithm.ResourceQuantity{Value: "100m", Format: "DecimalSI"}
			microservice.MemRequired = &algorithm.ResourceQuantity{Value: "100Mi", Format: "BinarySI"}
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
		// Safely get CPU and memory requirements
		if len(ms.Spec.Template.Spec.Containers) > 0 {
			container := &ms.Spec.Template.Spec.Containers[0]
			microservice.CpuRequired = getSafeResourceQuantity(container, corev1.ResourceCPU)
			microservice.MemRequired = getSafeResourceQuantity(container, corev1.ResourceMemory)
			fmt.Printf("From cluster - CPU: %s, Memory: %s for %s\n", microservice.CpuRequired.Value, microservice.MemRequired.Value, microservice.Name)
		} else {
			microservice.CpuRequired = &algorithm.ResourceQuantity{Value: "100m", Format: "DecimalSI"}
			microservice.MemRequired = &algorithm.ResourceQuantity{Value: "100Mi", Format: "BinarySI"}
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

	// Choose data source based on what's provided
	if deplfile != "" {
		// Load from file only if provided
		err = LoadWorkloadFromFile(deplfile, workload)
		if err != nil {
			return nil, err
		}
		fmt.Printf("Loaded %d microservices from file\n", len(workload.Microservices))
	} else if kubeclientset != nil {
		// Only load from cluster if file not provided
		err = LoadWorkloadFromCluster(kubeclientset, namespace, workload)
		if err != nil {
			return nil, err
		}
		fmt.Printf("Loaded %d microservices from cluster\n", len(workload.Microservices))
	}

	// Debug each microservice
	for _, ms := range workload.Microservices {
		fmt.Printf("DEBUG Microservice %s:\n", ms.Name)
		if ms.CpuRequired != nil {
			fmt.Printf("  CPU Value: '%s', Format: '%s'\n",
				ms.CpuRequired.Value, ms.CpuRequired.Format)
		} else {
			fmt.Printf("  CPU is NIL\n")
		}
		if ms.MemRequired != nil {
			fmt.Printf("  Mem Value: '%s', Format: '%s'\n",
				ms.MemRequired.Value, ms.MemRequired.Format)
		} else {
			fmt.Printf("  Mem is NIL\n")
		}
	}

	return workload, nil
}
