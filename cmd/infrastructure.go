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

	algorithm "gitlab.fbk.eu/fogatlas-k8s/algorithms/pkg/generated-go/idl"
	v1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/client-go/kubernetes"
)

// GetNodes function
func GetNodes(kubeclientset kubernetes.Interface) (nodes []*algorithm.Node, err error) {
	var nodeList *v1.NodeList

	nodeList, err = kubeclientset.CoreV1().Nodes().List(context.TODO(), metav1.ListOptions{})
	if err != nil {
		return nil, err
	}

	for _, n := range nodeList.Items {
		node := new(algorithm.Node)
		node.Name = n.Name
		node.Region = n.Labels["topology.kubernetes.io/region"]
		node.Subcategory = n.Labels["hardware.carbon/subcategory"]
		var cpuUsed, cpuCap, memCap, memUsed resource.Quantity
		selector := "spec.nodeName=" + n.Name
		pods, err := kubeclientset.CoreV1().Pods("").List(context.TODO(), metav1.ListOptions{FieldSelector: selector})
		if err != nil {
			return nil, err
		}
		for _, p := range pods.Items {
			for _, c := range p.Spec.Containers {
				cpuUsed.Add(*c.Resources.Requests.Cpu())
				memUsed.Add(*c.Resources.Requests.Memory())
			}
		}
		cpuCap.Add(*n.Status.Allocatable.Cpu())
		memCap.Add(*n.Status.Allocatable.Memory())
		node.CpuUsed = &algorithm.ResourceQuantity{
			Value:  cpuUsed.String(),
			Format: string(cpuUsed.Format),
		}
		node.CpuCap = &algorithm.ResourceQuantity{
			Value:  cpuCap.String(),
			Format: string(cpuCap.Format),
		}
		node.MemUsed = &algorithm.ResourceQuantity{
			Value:  memUsed.String(),
			Format: string(memUsed.Format),
		}
		node.MemCap = &algorithm.ResourceQuantity{
			Value:  memCap.String(),
			Format: string(memCap.Format),
		}
		nodes = append(nodes, node)
	}
	return nodes, nil
}

// LoadInfra function
func LoadInfra(kubeclientset kubernetes.Interface) (infra *algorithm.Infrastructure, err error) {

	infra = new(algorithm.Infrastructure)

	//get Nodes
	nodes, err := GetNodes(kubeclientset)
	if err != nil {
		return nil, err
	}

	infra.Nodes = nodes

	return infra, nil
}
