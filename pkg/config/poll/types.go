package poll

import (
	"k8s.io/test-infra/prow/kube"
)

// Configuration contains options for polling
// for changes against external APIs. Only one
// of the driver configurations should be non-
// empty.
type Configuration struct {
	ProwJob *ProwJob `json:"prow,omitempty"`
}

// ProwJob contains options for polling for
// changes to ProwJobs as a CRD on the host
// k8s cluster. In-cluster config will be
// used by default for connection.
type ProwJob struct {
	Namespace string `json:"namespace"`

	// Cluster is an optional specification
	// for connecting to a cluster.
	Cluster *kube.Cluster `json:"cluster,omitempty"`
}
