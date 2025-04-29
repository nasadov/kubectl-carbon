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
	"strconv"
	"strings"
	"time"

	log "github.com/sirupsen/logrus"
	"github.com/spf13/cobra"
	algorithm "gitlab.fbk.eu/fogatlas-k8s/algorithms/pkg/generated-go/idl"
	fav1alpha1 "gitlab.fbk.eu/fogatlas-k8s/crd-client-go/pkg/apis/fogatlas/v1alpha1"
	faclientset "gitlab.fbk.eu/fogatlas-k8s/crd-client-go/pkg/generated/clientset/versioned"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	v1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	k8serrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/cli-runtime/pkg/genericclioptions"
	"k8s.io/cli-runtime/pkg/genericiooptions"
	k8sclientset "k8s.io/client-go/kubernetes"
	"sigs.k8s.io/yaml"
)

var algorithmName string
var algorithmAddr string
var configFlags *genericclioptions.ConfigFlags
var logLevel string
var deplfilename string
var shrinkTimeFactor int

// Defines the COBRA command to be executed (carbon)
func NewCmdCarbon(streams genericiooptions.IOStreams) *cobra.Command {
	configFlags = genericclioptions.NewConfigFlags(true)

	carbonCmd := &cobra.Command{
		Use:   "carbon",
		Short: "Schedule workload according to the carbon-aware algorithm",
		Long: `This command allow an administrator to start a carbon-aware scheduling of submitted workload. 
			   Usage:
			   kubectl carbon -n [namespace] -a [algorithm name] -u [algorithm address] -f [deployment filename] -w [shrink time factor]`,
		RunE: func(cmd *cobra.Command, args []string) error {
			ConfigureLog()
			return carbon(cmd, args)
		},
	}

	carbonCmd.Flags().StringVarP(&algorithmName, "algorithm", "a", "carbon-aware", "Algorithm to use")
	carbonCmd.Flags().StringVarP(&algorithmAddr, "url", "u", "localhost:50051", "Address of the algorithm")
	carbonCmd.Flags().StringVarP(&logLevel, "loglevel", "l", "info", "Log level")
	carbonCmd.Flags().StringVarP(&deplfilename, "deplfile", "f", "", "Deployment manifest file")
	carbonCmd.Flags().IntVarP(&shrinkTimeFactor, "shrink", "w", 60, "Shrink time factor")

	configFlags.AddFlags(carbonCmd.Flags())
	if *configFlags.Namespace == "" {
		*configFlags.Namespace = "default"
	}

	return carbonCmd
}

func getClientSet(configFlags *genericclioptions.ConfigFlags) (*k8sclientset.Clientset, error) {
	config, err := configFlags.ToRESTConfig()
	if err != nil {
		log.Errorf("Unable to get config flags: (%s)", err.Error())
		return nil, err
	}

	// Adjust the QPS (queries per second) and burst settings
    config.QPS = 500
    config.Burst = 1000
	clientSet, err := k8sclientset.NewForConfig(config)
	if err != nil {
		log.Errorf("Unable to create k8s clientset: (%s)", err.Error())
		return nil, err
	}
	return clientSet, nil
}

func getFAClientSet(configFlags *genericclioptions.ConfigFlags) (*faclientset.Clientset, error) {
	config, err := configFlags.ToRESTConfig()
	if err != nil {
		log.Errorf("Unable to get config flags: (%s)", err.Error())
		return nil, err
	}

	// Adjust the QPS (queries per second) and burst settings
    config.QPS = 500
    config.Burst = 1000
	fogatlasClient, err := faclientset.NewForConfig(config)
	if err != nil {
		log.Errorf("Unable to create fa clientset: (%s)", err.Error())
		return nil, err
	}
	return fogatlasClient, nil
}

func initializeClients() (kubeClient *k8sclientset.Clientset, faClient *faclientset.Clientset, err error) {
	// Configure the access to the K8S API
	kubeClient, err = getClientSet(configFlags)
	if err != nil {
		log.Errorf("Error: unable to create kube clientset: (%s)", err.Error())
		return nil, nil, err
	}
	faClient, err = getFAClientSet(configFlags)
	if err != nil {
		log.Errorf("Error: unable to create fa clientset: (%s)", err.Error())
		return nil, nil, err
	}
	return kubeClient, faClient, nil

}

func initializeAlgorithm() (*algorithm.PlacementAlgorithmClient, error) {
	conn, err := grpc.Dial(algorithmAddr, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, err
	}
	c := algorithm.NewPlacementAlgorithmClient(conn)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second*10)
	defer cancel()
	// Call the remote method
	_, err = c.Init(ctx, &algorithm.AlgorithmName{Name: algorithmName})
	if err != nil {
		log.Errorf("Unable to initialize algorithm: (%s)", err.Error())
		return nil, err
	}

	return &c, nil
}

func handlePlacement(algorithmClient algorithm.PlacementAlgorithmClient, infra *algorithm.Infrastructure,
	workload *algorithm.Workload) (*algorithm.Placements, error) {
	data := algorithm.Data{
		Workload:       workload,
		Infrastructure: infra,
	}

	log.Debugf("Calling algorithm to calculate placement with following infrastructure: (%v)", data.Infrastructure)
	log.Debugf("Calling algorithm to calculate placement with following workload: (%v)", data.Workload)

	ctx, cancel := context.WithTimeout(context.Background(), time.Second*3600)
	defer cancel()

	results, err := algorithmClient.CalculatePlacement(ctx, &data)
	if err != nil {
		log.Errorf("Unable to calculate placement: (%s)", err.Error())
		return nil, err
	}
	log.Debugf("Placement results are: (%v)", results.Placements)
	return results, nil
}

func deployWorkload(kubeClient *k8sclientset.Clientset, placements []*algorithm.Placement) error {
	// create all deployments
	yamlFile, err := os.ReadFile(deplfilename)
	if err != nil {
		return err
	}

	// Split deployments
	depls := strings.Split(string(yamlFile), "---")
	gateName := "carbon-aware-scheduling-gate"
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

		// Add a schduling gate to the pod
		schedulingGate := corev1.PodSchedulingGate{
			Name: gateName,
		}
		if deployment.Spec.Template.Spec.SchedulingGates == nil {
			deployment.Spec.Template.Spec.SchedulingGates = []corev1.PodSchedulingGate{}
		}
		deployment.Spec.Template.Spec.SchedulingGates = append(deployment.Spec.Template.Spec.SchedulingGates, schedulingGate)

		// Add timeToSchedule as label to the pod
		timestamp := getTimestamp(deployment.Name, placements)
		deployment.Spec.Template.Labels["timeToSchedule"] = timestamp
		_, err = kubeClient.AppsV1().Deployments(*configFlags.Namespace).Create(context.TODO(), &deployment, metav1.CreateOptions{})
		if err != nil {
			log.Errorf("Unable to create deployments: (%s)", err.Error())
			return err
		}
	}
	return nil
}

func getTimestamp(deploymentName string, placements []*algorithm.Placement) string {
	currentTime := time.Now().Unix()
	for _, placement := range placements {
		if placement.MicroserviceName == deploymentName {
			scheduleTime := currentTime + int64((placement.TimeToSchedule-currentTime)/int64(shrinkTimeFactor))
			return strconv.FormatInt(scheduleTime, 10)
		}
	}
	// if not found, return time now as unix timestamp
	return strconv.FormatInt(currentTime, 10)
}

func savePlacementInfo(placements []*algorithm.Placement, timeNow int64, faclient faclientset.Interface) error {
	for _, place := range placements {
		placement := new(fav1alpha1.FAPlacement)
		placement.Name = place.MicroserviceName
		placement.APIVersion = "fogatlas.fbk.eu/v1alpha1"
		placement.Kind = "FAPlacement"
		placement.Namespace = *configFlags.Namespace
		placement.Spec.Microservice = place.MicroserviceName
		placement.Spec.UpdatedAt = timeNow
		for _, rs := range place.ReplicaScores {
			replicaScore := new(fav1alpha1.FAReplicaScores)
			for _, ns := range rs.Scores {
				nodeScore := new(fav1alpha1.FAScore)
				nodeScore.Node = ns.Node
				nodeScore.Score = ns.Score
				replicaScore.NodeScoreList = append(replicaScore.NodeScoreList, nodeScore)
			}
			placement.Spec.ReplicaScoreList = append(placement.Spec.ReplicaScoreList, replicaScore)
		}

		// Update FAPlacement
		p := placement.DeepCopy()
		pl, err := faclient.FogatlasV1alpha1().FAPlacements(*configFlags.Namespace).Get(context.TODO(), p.Name, metav1.GetOptions{})
		// If the resource doesn't exist, we'll create it
		if k8serrors.IsNotFound(err) {
			_, err = faclient.FogatlasV1alpha1().FAPlacements(*configFlags.Namespace).Create(context.TODO(), p, metav1.CreateOptions{})
		} else {
			p.SetResourceVersion(pl.GetResourceVersion())
			_, err = faclient.FogatlasV1alpha1().FAPlacements(*configFlags.Namespace).Update(context.TODO(), p, metav1.UpdateOptions{})
		}

		if err != nil {
			log.Errorf("Unable to save placements: (%s)", err.Error())
			return err
		}
	}
	return nil
}

// This is the function that implements the command
func carbon(cmd *cobra.Command, args []string) error {
	timeNow := time.Now().Unix()

	kubeClient, faClient, err := initializeClients()
	if err != nil {
		return err
	}

	log.Tracef("Flags are (%v)\n", cmd.Flags())
	log.Tracef("Args are (%v)\n", args)

	// Retrieve the cluster snapshot
	before := time.Now()
	infra, err := LoadInfra(kubeClient)
	if err != nil {
		log.Errorf("Error: unable to load infrastructure: (%s)", err.Error())
		return err
	}
	after := time.Now()
	log.Infof("<PERF> Elapsed time for LoadInfra is %v", after.Sub(before))
	before = time.Now()
	var workload *algorithm.Workload
	workload, err = LoadWorkload(kubeClient, *configFlags.Namespace, deplfilename)
	if err != nil {
		log.Errorf("Error: unable to load workload from cluster: (%s)", err.Error())
		return err
	}
	after = time.Now()
	log.Infof("<PERF> Elapsed time for GetWorkload is %v", after.Sub(before))
	log.Tracef("Infrastructure is: (%v)\n", infra)
	log.Tracef("Workload is : (%v)\n", workload)

	// Initialize the algorithm
	algorithmClient, err := initializeAlgorithm()
	if err != nil {
		log.Errorf("Error: unable to initialize algorithm: (%s)", err.Error())
		return err
	}

	// Call the algorithm
	before = time.Now()
	placementResults, err := handlePlacement(*algorithmClient, infra, workload)
	if err != nil {
		log.Errorf("Error: unable to get placement info: (%s)", err.Error())
		return err
	}
	after = time.Now()
	log.Infof("<PERF> Elapsed time for handlePlacement is %v", after.Sub(before))

	// Save placement info
	before = time.Now()
	err = savePlacementInfo(placementResults.Placements, timeNow, faClient)
	if err != nil {
		log.Errorf("Error: unable to save placement info: (%s)", err.Error())
		return err
	}
	after = time.Now()
	log.Infof("<PERF> Elapsed time for savePlacementInfo is %v", after.Sub(before))

	//Deploy the workload
	before = time.Now()
	err = deployWorkload(kubeClient, placementResults.Placements)
	if err != nil {
		log.Errorf("Error: unable to deploy the workload: (%s)", err.Error())
		return err
	}
	after = time.Now()
	log.Infof("<PERF> Elapsed time for deployment is %v", after.Sub(before))
	return nil
}

// configureLog function
func ConfigureLog() {
	var loggerLevel log.Level
	switch logLevel {
	case "trace":
		loggerLevel = log.TraceLevel
	case "debug":
		loggerLevel = log.DebugLevel
	case "info":
		loggerLevel = log.InfoLevel
	case "warn":
		loggerLevel = log.WarnLevel
	case "error":
		loggerLevel = log.ErrorLevel
	case "fatal":
		loggerLevel = log.FatalLevel
	case "panic":
		loggerLevel = log.PanicLevel
	default:
		loggerLevel = log.InfoLevel
	}

	log.SetLevel(loggerLevel)
	log.SetFormatter(&log.TextFormatter{
		DisableColors: false,
		FullTimestamp: true,
	})

}
