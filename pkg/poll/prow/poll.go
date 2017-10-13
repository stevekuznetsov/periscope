package prow

import (
	"fmt"
	"sync"

	"github.com/sirupsen/logrus"
	"k8s.io/test-infra/prow/kube"

	"github.com/stevekuznetsov/periscope/pkg/config/poll"
)

const (
	// maxWorkers is the maximum number of goroutines
	// that will be active at any one time
	maxWorkers = 20
)

func NewAgent(pollConfig *poll.ProwJob, logger *logrus.Entry) *Agent {
	return &Agent{
		pollConfig: pollConfig,
		logger:     logger,
	}
}

type Agent struct {
	pollConfig *poll.ProwJob
	logger     *logrus.Entry

	// cache holds the last known resourceVersion
	// for every ProwJob we process
	cache map[string]string
	// lock guards access to the cache
	lock sync.RWMutex
}

// MarkSeen marks the ProwJob processed at the
// specified version.
func (a *Agent) MarkSeen(uid, resourceVersion string) {
	a.lock.Lock()
	defer a.lock.Unlock()

	a.cache[uid] = resourceVersion
}

// Seen determines if we have previously processed
// this ProwJob at the specified version.
func (a *Agent) Seen(uid, resourceVersion string) bool {
	a.lock.Lock()
	defer a.lock.Unlock()

	lastVersion, exists := a.cache[uid]
	if !exists {
		return false
	}

	return resourceVersion == lastVersion
}

func (a *Agent) Run() error {
	var kclient *kube.Client
	var err error
	if a.pollConfig.Cluster != nil {
		kclient, err = kube.NewClient(a.pollConfig.Cluster, a.pollConfig.Namespace)
	} else {
		kclient, err = kube.NewClientInCluster(a.pollConfig.Namespace)
	}
	if err != nil {
		return fmt.Errorf("failed to get a client: %v", err)
	}
	a.logger.Infof("created a k8s client for namespace %q", a.pollConfig.Namespace)

	prowJobs, err := kclient.ListProwJobs(nil)
	if err != nil {
		return fmt.Errorf("failed to list prowjobs: %v", err)
	}

	actionableJobs := a.filterJobs(prowJobs)
	workQueue := make(chan kube.ProwJob, len(actionableJobs))
	for _, job := range actionableJobs {
		workQueue <- job
	}
	errCh := make(chan error, len(actionableJobs))

	wg := &sync.WaitGroup{}
	wg.Add(maxWorkers)
	for i := 0; i < maxWorkers; i++ {
		go func(jobs <-chan kube.ProwJob) {
			defer wg.Done()
			for job := range jobs {
				if err := a.updateDatabase(job); err != nil {
					errCh <- err
				}
			}
		}(workQueue)
	}

	updateErrors := []error{}
	for err := range errCh {
		updateErrors = append(updateErrors, err)
	}

	if len(updateErrors) > 0 {
		return fmt.Errorf("errors updating database: %v", updateErrors)
	}
	return nil
}

func (a *Agent) filterJobs(jobs []kube.ProwJob) []kube.ProwJob {
	filtered := jobs[:0]
	for _, job := range jobs {
		if !a.Seen(job.Metadata.UID, job.Metadata.ResourceVersion) {
			filtered = append(filtered, job)
		}
	}

	return filtered
}

func (a *Agent) updateDatabase(job kube.ProwJob) error {
	a.logger.WithField("job", job).Info("synced prowjob")
	return nil
}
