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
	"encoding/json"
	"encoding/xml"
	"errors"
	"flag"
	"fmt"
	"io/ioutil"
	"log"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	"k8s.io/test-infra/boskos/client"
)

// Hardcoded in ginkgo-e2e.sh
const defaultGinkgoParallel = 25

var (
	artifacts = filepath.Join(os.Getenv("WORKSPACE"), "_artifacts")
	interrupt = time.NewTimer(time.Duration(0)) // interrupt testing at this time.
	terminate = time.NewTimer(time.Duration(0)) // terminate testing at this time.
	verbose   = false
	timeout   = time.Duration(0)
	boskos    = client.NewClient(os.Getenv("JOB_NAME"), "http://boskos")
)

type options struct {
	build               buildStrategy
	charts              bool
	checkLeaks          bool
	checkSkew           bool
	cluster             string
	clusterIPRange      string
	deployment          string
	down                bool
	dump                string
	extract             extractStrategies
	federation          bool
	gcpCloudSdk         string
	gcpMasterImage      string
	gcpNetwork          string
	gcpNodeImage        string
	gcpNodes            string
	gcpProject          string
	gcpProjectType      string
	gcpServiceAccount   string
	gcpRegion           string
	gcpZone             string
	ginkgoParallel      ginkgoParallelValue
	kubemark            bool
	kubemarkMasterSize  string
	kubemarkNodes       string // TODO(fejta): switch to int after migration
	logexporterGCSPath  string
	metadataSources     string
	multiClusters       multiClusterDeployment
	multipleFederations bool
	nodeArgs            string
	nodeTestArgs        string
	nodeTests           bool
	perfTests           bool
	provider            string
	publish             string
	runtimeConfig       string
	save                string
	skew                bool
	stage               stageStrategy
	test                bool
	testArgs            string
	up                  bool
	upgradeArgs         string
}

func defineFlags() *options {
	o := options{}
	flag.Var(&o.build, "build", "Rebuild k8s binaries, optionally forcing (release|quick|bazel) stategy")
	flag.BoolVar(&o.charts, "charts", false, "If true, run charts tests")
	flag.BoolVar(&o.checkSkew, "check-version-skew", true, "Verify client and server versions match")
	flag.BoolVar(&o.checkLeaks, "check-leaked-resources", false, "Ensure project ends with the same resources")
	flag.StringVar(&o.cluster, "cluster", "", "Cluster name. Must be set for --deployment=gke (TODO: other deployments).")
	flag.StringVar(&o.clusterIPRange, "cluster-ip-range", "", "Specifies CLUSTER_IP_RANGE value during --up and --test (only relevant for --deployment=bash). Auto-calculated if empty.")
	flag.StringVar(&o.deployment, "deployment", "bash", "Choices: none/bash/gke/kops/kubernetes-anywhere/node")
	flag.BoolVar(&o.down, "down", false, "If true, tear down the cluster before exiting.")
	flag.StringVar(&o.dump, "dump", "", "If set, dump cluster logs to this location on test or cluster-up failure")
	flag.Var(&o.extract, "extract", "Extract k8s binaries from the specified release location")
	flag.BoolVar(&o.federation, "federation", false, "If true, start/tear down the federation control plane along with the clusters. To only start/tear down the federation control plane, specify --deployment=none")
	flag.Var(&o.ginkgoParallel, "ginkgo-parallel", fmt.Sprintf("Run Ginkgo tests in parallel, default %d runners. Use --ginkgo-parallel=N to specify an exact count.", defaultGinkgoParallel))
	flag.StringVar(&o.gcpCloudSdk, "gcp-cloud-sdk", "", "Install/upgrade google-cloud-sdk to the gs:// path if set")
	flag.StringVar(&o.gcpProject, "gcp-project", "", "For use with gcloud commands")
	flag.StringVar(&o.gcpProjectType, "gcp-project-type", "", "Explicitly indicate which project type to select from boskos")
	flag.StringVar(&o.gcpServiceAccount, "gcp-service-account", "", "Service account to activate before using gcloud")
	flag.StringVar(&o.gcpZone, "gcp-zone", "", "For use with gcloud commands")
	flag.StringVar(&o.gcpRegion, "gcp-region", "", "For use with gcloud commands")
	flag.StringVar(&o.gcpNetwork, "gcp-network", "", "Cluster network. Must be set for --deployment=gke (TODO: other deployments).")
	flag.StringVar(&o.gcpMasterImage, "gcp-master-image", "", "Master image type (cos|debian on GCE, n/a on GKE)")
	flag.StringVar(&o.gcpNodeImage, "gcp-node-image", "", "Node image type (cos|container_vm on GKE, cos|debian on GCE)")
	flag.StringVar(&o.gcpNodes, "gcp-nodes", "", "(--provider=gce only) Number of nodes to create.")
	flag.BoolVar(&o.kubemark, "kubemark", false, "If true, run kubemark tests.")
	flag.StringVar(&o.kubemarkMasterSize, "kubemark-master-size", "", "Kubemark master size (only relevant if --kubemark=true). Auto-calculated based on '--kubemark-nodes' if left empty.")
	flag.StringVar(&o.kubemarkNodes, "kubemark-nodes", "5", "Number of kubemark nodes to start (only relevant if --kubemark=true).")
	flag.StringVar(&o.logexporterGCSPath, "logexporter-gcs-path", "", "Path to the GCS artifacts directory to dump logs from nodes. Logexporter gets enabled if this is non-empty")
	flag.StringVar(&o.metadataSources, "metadata-sources", "images.json", "Comma-separated list of files inside ./artifacts to merge into metadata.json")
	flag.Var(&o.multiClusters, "multi-clusters", "If set, bring up/down multiple clusters specified. Format is [Zone1:]Cluster1[,[ZoneN:]ClusterN]]*. Zone is optional and default zone is used if zone is not specified")
	flag.BoolVar(&o.multipleFederations, "multiple-federations", false, "If true, enable running multiple federation control planes in parallel")
	flag.StringVar(&o.nodeArgs, "node-args", "", "Args for node e2e tests.")
	flag.StringVar(&o.nodeTestArgs, "node-test-args", "", "Test args specifically for node e2e tests.")
	flag.BoolVar(&o.nodeTests, "node-tests", false, "If true, run node-e2e tests.")
	flag.BoolVar(&o.perfTests, "perf-tests", false, "If true, run tests from perf-tests repo.")
	flag.StringVar(&o.provider, "provider", "", "Kubernetes provider such as gce, gke, aws, etc")
	flag.StringVar(&o.publish, "publish", "", "Publish version to the specified gs:// path on success")
	flag.StringVar(&o.runtimeConfig, "runtime-config", "batch/v2alpha1=true", "If set, API versions can be turned on or off while bringing up the API server.")
	flag.StringVar(&o.stage.dockerRegistry, "registry", "", "Push images to the specified docker registry (e.g. gcr.io/a-test-project)")
	flag.StringVar(&o.save, "save", "", "Save credentials to gs:// path on --up if set (or load from there if not --up)")
	flag.BoolVar(&o.skew, "skew", false, "If true, run tests in another version at ../kubernetes/hack/e2e.go")
	flag.Var(&o.stage, "stage", "Upload binaries to gs://bucket/devel/job-suffix if set")
	flag.StringVar(&o.stage.versionSuffix, "stage-suffix", "", "Append suffix to staged version when set")
	flag.BoolVar(&o.test, "test", false, "Run Ginkgo tests.")
	flag.StringVar(&o.testArgs, "test_args", "", "Space-separated list of arguments to pass to Ginkgo test runner.")
	flag.DurationVar(&timeout, "timeout", time.Duration(0), "Terminate testing after the timeout duration (s/m/h)")
	flag.BoolVar(&o.up, "up", false, "If true, start the the e2e cluster. If cluster is already up, recreate it.")
	flag.StringVar(&o.upgradeArgs, "upgrade_args", "", "If set, run upgrade tests before other tests")

	flag.BoolVar(&verbose, "v", false, "If true, print all command output.")
	return &o
}

type testCase struct {
	XMLName   xml.Name `xml:"testcase"`
	ClassName string   `xml:"classname,attr"`
	Name      string   `xml:"name,attr"`
	Time      float64  `xml:"time,attr"`
	Failure   string   `xml:"failure,omitempty"`
	Skipped   string   `xml:"skipped,omitempty"`
}

type testSuite struct {
	XMLName  xml.Name `xml:"testsuite"`
	Failures int      `xml:"failures,attr"`
	Tests    int      `xml:"tests,attr"`
	Time     float64  `xml:"time,attr"`
	Cases    []testCase
}

var suite testSuite

func validWorkingDirectory() error {
	cwd, err := os.Getwd()
	if err != nil {
		return fmt.Errorf("could not get pwd: %v", err)
	}
	acwd, err := filepath.Abs(cwd)
	if err != nil {
		return fmt.Errorf("failed to convert %s to an absolute path: %v", cwd, err)
	}
	// This also matches "kubernetes_skew" for upgrades.
	if !strings.Contains(filepath.Base(acwd), "kubernetes") {
		return fmt.Errorf("must run from kubernetes directory root: %v", acwd)
	}
	return nil
}

func writeXML(dump string, start time.Time) {
	suite.Time = time.Since(start).Seconds()
	out, err := xml.MarshalIndent(&suite, "", "    ")
	if err != nil {
		log.Fatalf("Could not marshal XML: %s", err)
	}
	path := filepath.Join(dump, "junit_runner.xml")
	f, err := os.Create(path)
	if err != nil {
		log.Fatalf("Could not create file: %s", err)
	}
	defer f.Close()
	if _, err := f.WriteString(xml.Header); err != nil {
		log.Fatalf("Error writing XML header: %s", err)
	}
	if _, err := f.Write(out); err != nil {
		log.Fatalf("Error writing XML data: %s", err)
	}
	log.Printf("Saved XML output to %s.", path)
}

type deployer interface {
	Up() error
	IsUp() error
	DumpClusterLogs(localPath, gcsPath string) error
	TestSetup() error
	Down() error
}

func getDeployer(o *options) (deployer, error) {
	switch o.deployment {
	case "bash":
		return newBash(&o.clusterIPRange), nil
	case "gke":
		return newGKE(o.provider, o.gcpProject, o.gcpZone, o.gcpRegion, o.gcpNetwork, o.gcpNodeImage, o.cluster, &o.testArgs, &o.upgradeArgs)
	case "kops":
		return newKops()
	case "kubernetes-anywhere":
		if o.multiClusters.Enabled() {
			return newKubernetesAnywhereMultiCluster(o.gcpProject, o.gcpZone, o.multiClusters)
		}
		return newKubernetesAnywhere(o.gcpProject, o.gcpZone)
	case "node":
		return nodeDeploy{}, nil
	case "none":
		return noneDeploy{}, nil
	default:
		return nil, fmt.Errorf("unknown deployment strategy %q", o.deployment)
	}
}

func validateFlags(o *options) error {
	if o.multiClusters.Enabled() && o.deployment != "kubernetes-anywhere" {
		return errors.New("--multi-clusters flag cannot be passed with deployments other than 'kubernetes-anywhere'")
	}
	return nil
}

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)
	o := defineFlags()
	flag.Parse()
	err := complete(o)

	if err := validateFlags(o); err != nil {
		log.Fatalf("Flags validation failed. err: %v", err)
	}

	if boskos.HasResource() {
		if berr := boskos.ReleaseAll("dirty"); berr != nil {
			log.Fatalf("[Boskos] Fail To Release: %v, kubetest err: %v", berr, err)
		}
	}

	if err != nil {
		log.Fatalf("Something went wrong: %v", err)
	}
}

func complete(o *options) error {
	if !terminate.Stop() {
		<-terminate.C // Drain the value if necessary.
	}
	if !interrupt.Stop() {
		<-interrupt.C // Drain value
	}

	if timeout > 0 {
		log.Printf("Limiting testing to %s", timeout)
		interrupt.Reset(timeout)
	}

	if o.dump != "" {
		defer writeMetadata(o.dump, o.metadataSources)
		defer writeXML(o.dump, time.Now())
	}
	if o.logexporterGCSPath != "" {
		o.testArgs += fmt.Sprintf(" --logexporter-gcs-path=%s", o.logexporterGCSPath)
	}
	if err := prepare(o); err != nil {
		return fmt.Errorf("failed to prepare test environment: %v", err)
	}
	if err := prepareFederation(o); err != nil {
		return fmt.Errorf("failed to prepare federation test environment: %v", err)
	}
	// Get the deployer before we acquire k8s so any additional flag
	// verifications happen early.
	deploy, err := getDeployer(o)
	if err != nil {
		return fmt.Errorf("error creating deployer: %v", err)
	}
	if err := acquireKubernetes(o); err != nil {
		return fmt.Errorf("failed to acquire k8s binaries: %v", err)
	}
	if err := validWorkingDirectory(); err != nil {
		return fmt.Errorf("called from invalid working directory: %v", err)
	}

	if o.down {
		// listen for signals such as ^C and gracefully attempt to clean up
		c := make(chan os.Signal, 1)
		signal.Notify(c, os.Interrupt)
		go func() {
			for range c {
				log.Print("Captured ^C, gracefully attempting to cleanup resources..")
				var fedErr, err error
				if o.federation {
					if fedErr = fedDown(); fedErr != nil {
						log.Printf("Tearing down federation failed: %v", fedErr)
					}
				}
				if err = deploy.Down(); err != nil {
					log.Printf("Tearing down deployment failed: %v", err)
				}
				if fedErr != nil || err != nil {
					os.Exit(1)
				}
			}
		}()
	}

	if err := run(deploy, *o); err != nil {
		return err
	}

	// Save the state if we upped a new cluster without downing it
	// or we are turning up federated clusters without turning up
	// the federation control plane.
	if o.save != "" && ((!o.down && o.up) || (!o.federation && o.up && o.deployment != "none")) {
		if err := saveState(o.save); err != nil {
			return err
		}
	}

	// Publish the successfully tested version when requested
	if o.publish != "" {
		if err := publish(o.publish); err != nil {
			return err
		}
	}
	return nil
}

func acquireKubernetes(o *options) error {
	// Potentially build kubernetes
	if o.build.Enabled() {
		if err := xmlWrap("Build", o.build.Build); err != nil {
			return err
		}
	}

	// Potentially stage build binaries somewhere on GCS
	if o.stage.Enabled() {
		if err := xmlWrap("Stage", func() error {
			return o.stage.Stage(o.federation)
		}); err != nil {
			return err
		}
	}

	// Potentially download existing binaries and extract them.
	if o.extract.Enabled() {
		err := xmlWrap("Extract", func() error {
			// Should we restore a previous state?
			// Restore if we are not upping the cluster or we are bringing up
			// a federation control plane without the federated clusters.
			if o.save != "" {
				if !o.up {
					// Restore version and .kube/config from --up
					log.Printf("Overwriting extract strategy to load kubeconfig and version from %s", o.save)
					o.extract = extractStrategies{extractStrategy{mode: load, option: o.save}}
				} else if o.federation && o.up && o.deployment == "none" {
					// Only restore .kube/config from previous --up, use the regular
					// extraction strategy to restore version.
					log.Printf("Load kubeconfig from %s", o.save)
					loadKubeconfig(o.save)
				}
			}
			// New deployment, extract new version
			return o.extract.Extract(o.gcpProject, o.gcpZone)
		})
		if err != nil {
			return err
		}
	}
	return nil
}

// Returns the k8s version name
func findVersion() string {
	// The version may be in a version file
	if _, err := os.Stat("version"); err == nil {
		b, err := ioutil.ReadFile("version")
		if err == nil {
			return strings.TrimSpace(string(b))
		}
		log.Printf("Failed to read version: %v", err)
	}

	// We can also get it from the git repo.
	if _, err := os.Stat("hack/lib/version.sh"); err == nil {
		// TODO(fejta): do this in go. At least we removed the upload-to-gcs.sh dep.
		gross := `. hack/lib/version.sh && KUBE_ROOT=. kube::version::get_version_vars && echo "${KUBE_GIT_VERSION-}"`
		b, err := output(exec.Command("bash", "-c", gross))
		if err == nil {
			return strings.TrimSpace(string(b))
		}
		log.Printf("Failed to get_version_vars: %v", err)
	}

	return "unknown" // Sad trombone
}

// maybeMergeMetadata will add new keyvals into the map; quietly eats errors.
func maybeMergeJSON(meta map[string]string, path string) {
	if data, err := ioutil.ReadFile(path); err == nil {
		json.Unmarshal(data, &meta)
	}
}

// Write metadata.json, including version and env arg data.
func writeMetadata(path, metadataSources string) error {
	m := make(map[string]string)

	// Look for any sources of metadata and load 'em
	for _, f := range strings.Split(metadataSources, ",") {
		maybeMergeJSON(m, filepath.Join(path, f))
	}

	ver := findVersion()
	m["version"] = ver // TODO(fejta): retire
	m["job-version"] = ver
	re := regexp.MustCompile(`^BUILD_METADATA_(.+)$`)
	for _, e := range os.Environ() {
		p := strings.SplitN(e, "=", 2)
		r := re.FindStringSubmatch(p[0])
		if r == nil {
			continue
		}
		k, v := strings.ToLower(r[1]), p[1]
		m[k] = v
	}
	f, err := os.Create(filepath.Join(path, "metadata.json"))
	if err != nil {
		return err
	}
	defer f.Close()
	e := json.NewEncoder(f)
	return e.Encode(m)
}

// Install cloudsdk tarball to location, updating PATH
func installGcloud(tarball string, location string) error {

	if err := os.MkdirAll(location, 0775); err != nil {
		return err
	}

	if err := finishRunning(exec.Command("tar", "xzf", tarball, "-C", location)); err != nil {
		return err
	}

	if err := finishRunning(exec.Command(filepath.Join(location, "google-cloud-sdk", "install.sh"), "--disable-installation-options", "--bash-completion=false", "--path-update=false", "--usage-reporting=false")); err != nil {
		return err
	}

	if err := insertPath(filepath.Join(location, "google-cloud-sdk", "bin")); err != nil {
		return err
	}

	if err := finishRunning(exec.Command("gcloud", "components", "install", "alpha")); err != nil {
		return err
	}

	if err := finishRunning(exec.Command("gcloud", "components", "install", "beta")); err != nil {
		return err
	}

	if err := finishRunning(exec.Command("gcloud", "info")); err != nil {
		return err
	}
	return nil
}

func migrateGcpEnvAndOptions(o *options) error {
	var network string
	var zone string
	switch o.provider {
	case "gke":
		network = "KUBE_GKE_NETWORK"
		zone = "ZONE"
	default:
		network = "KUBE_GCE_NETWORK"
		zone = "KUBE_GCE_ZONE"
	}
	return migrateOptions([]migratedOption{
		{
			env:    "PROJECT",
			option: &o.gcpProject,
			name:   "--gcp-project",
		},
		{
			env:    zone,
			option: &o.gcpZone,
			name:   "--gcp-zone",
		},
		{
			env:    "REGION",
			option: &o.gcpRegion,
			name:   "--gcp-region",
		},
		{
			env:    "GOOGLE_APPLICATION_CREDENTIALS",
			option: &o.gcpServiceAccount,
			name:   "--gcp-service-account",
		},
		{
			env:    network,
			option: &o.gcpNetwork,
			name:   "--gcp-network",
		},
		{
			env:    "KUBE_NODE_OS_DISTRIBUTION",
			option: &o.gcpNodeImage,
			name:   "--gcp-node-image",
		},
		{
			env:    "KUBE_MASTER_OS_DISTRIBUTION",
			option: &o.gcpMasterImage,
			name:   "--gcp-master-image",
		},
		{
			env:    "NUM_NODES",
			option: &o.gcpNodes,
			name:   "--gcp-nodes",
		},
		{
			env:      "CLOUDSDK_BUCKET",
			option:   &o.gcpCloudSdk,
			name:     "--gcp-cloud-sdk",
			skipPush: true,
		},
	})
}

func prepareGcp(o *options) error {
	if err := migrateGcpEnvAndOptions(o); err != nil {
		return err
	}
	if o.provider == "gce" {
		if distro := os.Getenv("KUBE_OS_DISTRIBUTION"); distro != "" {
			log.Printf("Please use --gcp-master-image=%s --gcp-node-image=%s (instead of deprecated KUBE_OS_DISTRIBUTION)",
				distro, distro)
			// Note: KUBE_OS_DISTRIBUTION takes precedence over
			// KUBE_{MASTER,NODE}_OS_DISTRIBUTION, so override here
			// after the migration above.
			o.gcpNodeImage = distro
			o.gcpMasterImage = distro
			if err := os.Setenv("KUBE_NODE_OS_DISTRIBUTION", distro); err != nil {
				return fmt.Errorf("could not set KUBE_NODE_OS_DISTRIBUTION=%s: %v", distro, err)
			}
			if err := os.Setenv("KUBE_MASTER_OS_DISTRIBUTION", distro); err != nil {
				return fmt.Errorf("could not set KUBE_MASTER_OS_DISTRIBUTION=%s: %v", distro, err)
			}
		}
	} else if o.provider == "gke" {
		if o.deployment == "" {
			o.deployment = "gke"
		}
		if o.deployment != "gke" {
			return fmt.Errorf("--provider=gke implies --deployment=gke")
		}
		if o.gcpNodeImage == "" {
			return fmt.Errorf("--gcp-node-image must be set for GKE")
		}
		if o.gcpMasterImage != "" {
			return fmt.Errorf("--gcp-master-image cannot be set on GKE")
		}
		if o.gcpNodes != "" {
			return fmt.Errorf("--gcp-nodes cannot be set on GKE, use --gke-shape instead")
		}

		// TODO(kubernetes/test-infra#3536): This is used by the
		// ginkgo-e2e.sh wrapper.
		nod := o.gcpNodeImage
		if nod == "container_vm" {
			// gcloud container clusters create understands
			// "container_vm", e2es understand "debian".
			nod = "debian"
		}
		os.Setenv("NODE_OS_DISTRIBUTION", nod)
	}
	if o.gcpProject == "" {
		var resType string
		if o.gcpProjectType != "" {
			resType = o.gcpProjectType
		} else if o.provider == "gke" {
			resType = "gke-project"
		} else {
			resType = "gce-project"
		}

		log.Printf("provider %v, will acquire resource %v from boskos", o.provider, resType)

		p, err := boskos.Acquire(resType, "free", "busy")
		if err != nil {
			return fmt.Errorf("--provider=%s boskos failed to acquire project: %v", o.provider, err)
		}

		if p == "" {
			return fmt.Errorf("boskos does not have a free %s at the moment", resType)
		}

		go func(c *client.Client, proj string) {
			for range time.Tick(time.Minute * 5) {
				if err := c.UpdateOne(p, "busy"); err != nil {
					log.Printf("[Boskos] Update %s failed with %v", p, err)
				}
			}
		}(boskos, p)
		o.gcpProject = p
	}

	if err := os.Setenv("CLOUDSDK_CORE_PRINT_UNHANDLED_TRACEBACKS", "1"); err != nil {
		return fmt.Errorf("could not set CLOUDSDK_CORE_PRINT_UNHANDLED_TRACEBACKS=1: %v", err)
	}

	if err := finishRunning(exec.Command("gcloud", "config", "set", "project", o.gcpProject)); err != nil {
		return fmt.Errorf("fail to set project %s : err %v", o.gcpProject, err)
	}

	// TODO(krzyzacy):Remove this when we retire migrateGcpEnvAndOptions
	// Note that a lot of scripts are still depend on this env in k/k repo.
	if err := os.Setenv("PROJECT", o.gcpProject); err != nil {
		return fmt.Errorf("fail to set env var PROJECT %s : err %v", o.gcpProject, err)
	}

	// gcloud creds may have changed
	if err := activateServiceAccount(o.gcpServiceAccount); err != nil {
		return err
	}

	// Ensure ssh keys exist
	log.Print("Checking existing of GCP ssh keys...")
	k := filepath.Join(home(".ssh"), "google_compute_engine")
	if _, err := os.Stat(k); err != nil {
		return err
	}
	pk := k + ".pub"
	if _, err := os.Stat(pk); err != nil {
		return err
	}

	log.Printf("Checking presence of public key in %s", o.gcpProject)
	if out, err := output(exec.Command("gcloud", "compute", "--project="+o.gcpProject, "project-info", "describe")); err != nil {
		return err
	} else if b, err := ioutil.ReadFile(pk); err != nil {
		return err
	} else if !strings.Contains(string(b), string(out)) {
		log.Print("Uploading public ssh key to project metadata...")
		if err = finishRunning(exec.Command("gcloud", "compute", "--project="+o.gcpProject, "config-ssh")); err != nil {
			return err
		}
	}

	// Install custom gcloud verion if necessary
	if o.gcpCloudSdk != "" {
		for i := 0; i < 3; i++ {
			if err := finishRunning(exec.Command("gsutil", "-mq", "cp", "-r", o.gcpCloudSdk, home())); err == nil {
				break // Success!
			}
			time.Sleep(1 << uint(i) * time.Second)
		}
		for _, f := range []string{home(".gsutil"), home("repo"), home("cloudsdk")} {
			if _, err := os.Stat(f); err == nil || !os.IsNotExist(err) {
				if err = os.RemoveAll(f); err != nil {
					return err
				}
			}
		}

		install := home("repo", "google-cloud-sdk.tar.gz")
		if strings.HasSuffix(o.gcpCloudSdk, ".tar.gz") {
			install = home(filepath.Base(o.gcpCloudSdk))
		} else {
			if err := os.Rename(home(filepath.Base(o.gcpCloudSdk)), home("repo")); err != nil {
				return err
			}

			// Controls which gcloud components to install.
			pop, err := pushEnv("CLOUDSDK_COMPONENT_MANAGER_SNAPSHOT_URL", "file://"+home("repo", "components-2.json"))
			if err != nil {
				return err
			}
			defer pop()
		}

		if err := installGcloud(install, home("cloudsdk")); err != nil {
			return err
		}
		// gcloud creds may have changed
		if err := activateServiceAccount(o.gcpServiceAccount); err != nil {
			return err
		}
	}
	return nil
}

func prepareAws(o *options) error {
	// gcloud creds may have changed
	if err := activateServiceAccount(o.gcpServiceAccount); err != nil {
		return err
	}
	return finishRunning(exec.Command("pip", "install", "awscli"))
}

// Activate GOOGLE_APPLICATION_CREDENTIALS if set or do nothing.
func activateServiceAccount(path string) error {
	if path == "" {
		return nil
	}
	return finishRunning(exec.Command("gcloud", "auth", "activate-service-account", "--key-file="+path))
}

// Make all artifacts world readable.
// The root user winds up owning the files when the container exists.
// Ensure that other users can read these files at that time.
func chmodArtifacts() error {
	return finishRunning(exec.Command("chmod", "-R", "o+r", artifacts))
}

func prepare(o *options) error {
	if err := migrateOptions([]migratedOption{
		{
			env:    "KUBERNETES_PROVIDER",
			option: &o.provider,
			name:   "--provider",
		},
		{
			env:    "CLUSTER_NAME",
			option: &o.cluster,
			name:   "--cluster",
		},
	}); err != nil {
		return err
	}
	if err := prepareGinkgoParallel(&o.ginkgoParallel); err != nil {
		return err
	}

	switch o.provider {
	case "gce", "gke", "kubernetes-anywhere", "node":
		if err := prepareGcp(o); err != nil {
			return err
		}
	case "aws":
		if err := prepareAws(o); err != nil {
			return err
		}
	}

	if o.kubemark {
		if err := migrateOptions([]migratedOption{
			{
				env:    "KUBEMARK_NUM_NODES",
				option: &o.kubemarkNodes,
				name:   "--kubemark-nodes",
			},
			{
				env:    "KUBEMARK_MASTER_SIZE",
				option: &o.kubemarkMasterSize,
				name:   "--kubemark-master-size",
			},
		}); err != nil {
			return err
		}
	}

	if err := os.MkdirAll(artifacts, 0777); err != nil { // Create artifacts
		return err
	}

	return nil
}

func prepareFederation(o *options) error {
	if o.multipleFederations {
		// TODO(fejta): use boskos to grab a federation cluster
		// Note: EXECUTOR_NUMBER and NODE_NAME are Jenkins
		// specific environment variables. So this doesn't work
		// when we move away from Jenkins.
		execNum := os.Getenv("EXECUTOR_NUMBER")
		if execNum == "" {
			execNum = "0"
		}
		suffix := fmt.Sprintf("%s-%s", os.Getenv("NODE_NAME"), execNum)
		federationName := fmt.Sprintf("e2e-f8n-%s", suffix)
		federationSystemNamespace := fmt.Sprintf("f8n-system-%s", suffix)
		err := os.Setenv("FEDERATION_NAME", federationName)
		if err != nil {
			return err
		}
		return os.Setenv("FEDERATION_NAMESPACE", federationSystemNamespace)
	}
	return nil
}

type ginkgoParallelValue struct {
	v int // 0 == not set (defaults to 1)
}

func (v *ginkgoParallelValue) IsBoolFlag() bool {
	return true
}

func (v *ginkgoParallelValue) String() string {
	if v.v == 0 {
		return "1"
	}
	return strconv.Itoa(v.v)
}

func (v *ginkgoParallelValue) Set(s string) error {
	if s == "" {
		v.v = 0
		return nil
	}
	if s == "true" {
		v.v = defaultGinkgoParallel
		return nil
	}
	p, err := strconv.Atoi(s)
	if err != nil {
		return fmt.Errorf("--ginkgo-parallel must be an integer, found %q", s)
	}
	if p < 1 {
		return fmt.Errorf("--ginkgo-parallel must be >= 1, found %d", p)
	}
	v.v = p
	return nil
}

func (v *ginkgoParallelValue) Get() int {
	if v.v == 0 {
		return 1
	}
	return v.v
}

var _ flag.Value = &ginkgoParallelValue{}

// Hand migrate this option. GINKGO_PARALLEL => GINKGO_PARALLEL_NODES=25
func prepareGinkgoParallel(v *ginkgoParallelValue) error {
	if p := os.Getenv("GINKGO_PARALLEL"); strings.ToLower(p) == "y" {
		log.Printf("Please use kubetest --ginkgo-parallel (instead of deprecated GINKGO_PARALLEL=y)")
		if err := v.Set("true"); err != nil {
			return err
		}
		os.Unsetenv("GINKGO_PARALLEL")
	}
	if p := os.Getenv("GINKGO_PARALLEL_NODES"); p != "" {
		log.Printf("Please use kubetest --ginkgo-parallel=%s (instead of deprecated GINKGO_PARALLEL_NODES=%s)", p, p)
		if err := v.Set(p); err != nil {
			return err
		}
	}
	os.Setenv("GINKGO_PARALLEL_NODES", v.String())
	return nil
}

func publish(pub string) error {
	v, err := ioutil.ReadFile("version")
	if err != nil {
		return err
	}
	log.Printf("Set %s version to %s", pub, string(v))
	return finishRunning(exec.Command("gsutil", "cp", "version", pub))
}
