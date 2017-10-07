/*
Copyright 2017 The Kubernetes Authors.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package main

import (
	"flag"
	"fmt"
	"io/ioutil"
	"os"
	"os/exec"
	"os/user"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

var (
	// kops specific flags.
	kopsPath         = flag.String("kops", "", "(kops only) Path to the kops binary. Must be set for kops.")
	kopsCluster      = flag.String("kops-cluster", "", "(kops only) Cluster name. Must be set for kops.")
	kopsState        = flag.String("kops-state", "", "(kops only) s3:// path to kops state store. Must be set.")
	kopsSSHKey       = flag.String("kops-ssh-key", "", "(kops only) Path to ssh key-pair for each node (defaults '~/.ssh/kube_aws_rsa' if unset.)")
	kopsKubeVersion  = flag.String("kops-kubernetes-version", "", "(kops only) If set, the version of Kubernetes to deploy (can be a URL to a GCS path where the release is stored) (Defaults to kops default, latest stable release.).")
	kopsZones        = flag.String("kops-zones", "us-west-2a", "(kops AWS only) AWS zones for kops deployment, comma delimited.")
	kopsNodes        = flag.Int("kops-nodes", 2, "(kops only) Number of nodes to create.")
	kopsUpTimeout    = flag.Duration("kops-up-timeout", 20*time.Minute, "(kops only) Time limit between 'kops config / kops update' and a response from the Kubernetes API.")
	kopsAdminAccess  = flag.String("kops-admin-access", "", "(kops only) If set, restrict apiserver access to this CIDR range.")
	kopsImage        = flag.String("kops-image", "", "(kops only) Image (AMI) for nodes to use. (Defaults to kops default, a Debian image with a custom kubernetes kernel.)")
	kopsArgs         = flag.String("kops-args", "", "(kops only) Additional space-separated args to pass unvalidated to 'kops create cluster', e.g. '--kops-args=\"--dns private --node-size t2.micro\"'")
	kopsPriorityPath = flag.String("kops-priority-path", "", "Insert into PATH if set")
)

type kops struct {
	path        string
	kubeVersion string
	sshKey      string
	zones       []string
	nodes       int
	adminAccess string
	cluster     string
	image       string
	args        string
	kubecfg     string
}

var _ deployer = kops{}

func migrateKopsEnv() error {
	return migrateOptions([]migratedOption{
		{
			env:      "KOPS_STATE_STORE",
			option:   kopsState,
			name:     "--kops-state",
			skipPush: true,
		},
		{
			env:      "AWS_SSH_KEY",
			option:   kopsSSHKey,
			name:     "--kops-ssh-key",
			skipPush: true,
		},
		{
			env:      "PRIORITY_PATH",
			option:   kopsPriorityPath,
			name:     "--kops-priority-path",
			skipPush: true,
		},
	})
}

func newKops() (*kops, error) {
	if err := migrateKopsEnv(); err != nil {
		return nil, err
	}
	if *kopsPath == "" {
		return nil, fmt.Errorf("--kops must be set to a valid binary path for kops deployment")
	}
	if *kopsCluster == "" {
		return nil, fmt.Errorf("--kops-cluster must be set to a valid cluster name for kops deployment")
	}
	if *kopsState == "" {
		return nil, fmt.Errorf("--kops-state must be set to a valid S3 path for kops deployment")
	}
	if *kopsPriorityPath != "" {
		if err := insertPath(*kopsPriorityPath); err != nil {
			return nil, err
		}
	}

	// TODO(fejta): consider explicitly passing these env items where needed.
	sshKey := *kopsSSHKey
	if sshKey == "" {
		usr, err := user.Current()
		if err != nil {
			return nil, err
		}
		sshKey = filepath.Join(usr.HomeDir, ".ssh/kube_aws_rsa")
	}
	if err := os.Setenv("KOPS_STATE_STORE", *kopsState); err != nil {
		return nil, err
	}
	f, err := ioutil.TempFile("", "kops-kubecfg")
	if err != nil {
		return nil, err
	}
	defer f.Close()
	kubecfg := f.Name()
	if err := f.Chmod(0600); err != nil {
		return nil, err
	}
	if err := os.Setenv("KUBECONFIG", kubecfg); err != nil {
		return nil, err
	}
	// Set KUBERNETES_CONFORMANCE_TEST so the auth info is picked up
	// from kubectl instead of bash inference.
	if err := os.Setenv("KUBERNETES_CONFORMANCE_TEST", "yes"); err != nil {
		return nil, err
	}
	// Set KUBERNETES_CONFORMANCE_PROVIDER to override the
	// cloudprovider for KUBERNETES_CONFORMANCE_TEST.
	if err := os.Setenv("KUBERNETES_CONFORMANCE_PROVIDER", "aws"); err != nil {
		return nil, err
	}
	// AWS_SSH_KEY is required by the AWS e2e tests.
	if err := os.Setenv("AWS_SSH_KEY", sshKey); err != nil {
		return nil, err
	}
	// ZONE is required by the AWS e2e tests.
	zones := strings.Split(*kopsZones, ",")
	if err := os.Setenv("ZONE", zones[0]); err != nil {
		return nil, err
	}
	return &kops{
		path:        *kopsPath,
		kubeVersion: *kopsKubeVersion,
		sshKey:      sshKey + ".pub", // kops only needs the public key, e2es need the private key.
		zones:       zones,
		nodes:       *kopsNodes,
		adminAccess: *kopsAdminAccess,
		cluster:     *kopsCluster,
		image:       *kopsImage,
		args:        *kopsArgs,
		kubecfg:     kubecfg,
	}, nil
}

func (k kops) Up() error {
	createArgs := []string{
		"create", "cluster",
		"--name", k.cluster,
		"--ssh-public-key", k.sshKey,
		"--node-count", strconv.Itoa(k.nodes),
		"--zones", strings.Join(k.zones, ","),
	}
	if k.kubeVersion != "" {
		createArgs = append(createArgs, "--kubernetes-version", k.kubeVersion)
	}
	if k.adminAccess != "" {
		createArgs = append(createArgs, "--admin-access", k.adminAccess)
	}
	if k.image != "" {
		createArgs = append(createArgs, "--image", k.image)
	}
	if k.args != "" {
		createArgs = append(createArgs, strings.Split(k.args, " ")...)
	}
	if err := finishRunning(exec.Command(k.path, createArgs...)); err != nil {
		return fmt.Errorf("kops configuration failed: %v", err)
	}
	if err := finishRunning(exec.Command(k.path, "update", "cluster", k.cluster, "--yes")); err != nil {
		return fmt.Errorf("kops bringup failed: %v", err)
	}
	// TODO(zmerlynn): More cluster validation. This should perhaps be
	// added to kops and not here, but this is a fine place to loop
	// for now.
	return waitForNodes(k, k.nodes+1, *kopsUpTimeout)
}

func (k kops) IsUp() error {
	return isUp(k)
}

func (k kops) DumpClusterLogs(localPath, gcsPath string) error {
	return defaultDumpClusterLogs(localPath, gcsPath)
}

func (k kops) TestSetup() error {
	info, err := os.Stat(k.kubecfg)
	if err != nil {
		return err
	}
	if info.Size() > 0 {
		// Assume that if we already have it, it's good.
		return nil
	}
	if err := finishRunning(exec.Command(k.path, "export", "kubecfg", k.cluster)); err != nil {
		return fmt.Errorf("Failure exporting kops kubecfg: %v", err)
	}
	return nil
}

func (k kops) Down() error {
	// We do a "kops get" first so the exit status of "kops delete" is
	// more sensical in the case of a non-existent cluster. ("kops
	// delete" will exit with status 1 on a non-existent cluster)
	err := finishRunning(exec.Command(k.path, "get", "clusters", k.cluster))
	if err != nil {
		// This is expected if the cluster doesn't exist.
		return nil
	}
	return finishRunning(exec.Command(k.path, "delete", "cluster", k.cluster, "--yes"))
}
