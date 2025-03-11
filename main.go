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

package main

import (
	"os"

	"github.com/spf13/pflag"
	"gitlab.fbk.eu/fogatlas-k8s/kubectl-carbon/cmd"
	"k8s.io/cli-runtime/pkg/genericiooptions"
)

func main() {
	flags := pflag.NewFlagSet("kubectl-carbon", pflag.ExitOnError)
	pflag.CommandLine = flags

	carbonCmd := cmd.NewCmdCarbon(genericiooptions.IOStreams{In: os.Stdin, Out: os.Stdout, ErrOut: os.Stderr})
	if err := carbonCmd.Execute(); err != nil {
		os.Exit(1)
	}
}
