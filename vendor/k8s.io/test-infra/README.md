# Kubernetes Test Infrastructure

[![Build Status](https://travis-ci.org/kubernetes/test-infra.svg?branch=master)](https://travis-ci.org/kubernetes/test-infra)  [![Go Report Card](https://goreportcard.com/badge/github.com/kubernetes/test-infra)](https://goreportcard.com/report/github.com/kubernetes/test-infra)  [![GoDoc](https://godoc.org/github.com/kubernetes/test-infra?status.svg)](https://godoc.org/github.com/kubernetes/test-infra)

The test-infra repository contains a collection of tools for testing Kubernetes
and displaying Kubernetes tests results. See also [CONTRIBUTING.md](CONTRIBUTING.md).

See the [architecture diagram](docs/architecture.svg) for an overview of how
the different services interact.

## Viewing test results

* The [Kubernetes TestGrid](https://k8s-testgrid.appspot.com/) shows historical test results
  - Configure your own testgrid dashboard at [testgrid/config/config.yaml](testgrid/config/config.yaml)
  - [Gubernator](https://k8s-gubernator.appspot.com/) formats the output of each run
* [PR Dashboard](https://k8s-gubernator.appspot.com/pr) finds PRs that need your attention
* [Prow](https://prow.k8s.io) schedules testing and updates issues
  - Prow responds to GitHub events, timers and manual commands
  - The [prow dashboard](https://prow.k8s.io/) shows what it is currently testing
  - Configure prow to run new tests at [prow/config.yaml](prow/config.yaml)
* [Triage Dashboard](https://go.k8s.io/triage) aggregates failures
  - Triage clusters together similar failures
  - Search for test failures across jobs
  - Filter down failures in a specific regex of tests and/or jobs
* [Test history](https://go.k8s.io/test-history) is a deprecated tool
  - Use the triage dashboard instead
  - Summarizes the last 24 hours of testing
  - See [Kettle](kettle) and the corresponding [bigquery metrics](metrics) that largely supplement this information


## Automated testing

Test anything with the following pattern:

```
git clone https://github.com/kubernetes/test-infra
test-infra/jenkins/bootstrap.py --job=J --repo=R --service-account=S.json --upload=gs://B
```

The `--job=J` flag specifies what test job to run.
The `--repo=R` (or `--bare`) flag controls what we check out from git.

Anyone can reconfigure our CI system with a test-infra PR that updates the
appropriate files. Detailed instructions follow:

### E2E Testing

Our e2e testing uses [kubetest](/kubetest) to build/deploy/test kubernetes
clusters on various providers. Please see those documents for additional details
about this tool as well as e2e testing generally.

### Create a new job

Create a PR in this repo to add/update/remove a job or suite. Specifically
you'll need to do the following:
* Create an entry in [`jobs/config.json`] for the job
  - If this is a kubetest job create the corresponding `jobs/env/FOO.env` file
  - It will pick a free project from [boskos](/boskos) pool by default, or
  - You can also set --gcp-project=foo in [`jobs/config.json`] for a dedicated project, make sure the project has the right [IAM grants](jenkins/check_projects.py)
* Add the job name to the `test_groups` list in [`testgrid/config/config.yaml`](https://github.com/kubernetes/test-infra/blob/master/testgrid/config/config.yaml)
  - Also the group to at least one `dashboard_tab`
* Add the job to the appropriate section in [`prow/config.yaml`](https://github.com/kubernetes/test-infra/blob/master/prow/config.yaml)
  - Presubmit jobs run on unmerged code in PRs
  - Postsubmit jobs run after merging code
  - Periodic job run on a timed basis
* (Deprecated!) Some old jobs still run on jenkins
  - Please do not add new jobs to jenkins
  - Jenkins configuration is defined at `jenkins/job-configs`
  - More deprecated details at [jenkins/README.md](jenkins/README.md)

NOTE: `kubernetes/kubernetes` and `kubernetes-security/kubernetes` must have matching presubmits.

Please test the job on your local workstation before creating a PR:
```
mkdir /tmp/whatever && cd /tmp/whatever
$GOPATH/src/k8s.io/test-infra/jenkins/bootstrap.py \
  --job=J \  # aka your new job
  --repo=R1 --repo=R2 \  # what repos to check out
  --service-account ~/S.json  # the service account to use to launch GCE/GKE clusters
# Note: create a service account at the cloud console for the project J uses
```

Presubmit will tell you if you forget to do any of this correctly.

Merge your PR and the bot will deploy your change automatically.

### Update an existing job

Largely similar to creating a new job, except you can just modify the existing
entries rather than adding new ones.

Update what a job does by editing its definition in [`jobs/config.json`]. For
the kubetest jobs this typically means editing the `jobs/FOO.env` files it uses.

Update when a job runs by changing its definition in [`prow/config.yaml`].
The [test-infra oncall] must push prow changes (`make -C prow update-config`).

Update where the job appears on testgrid by changing [`testgrid/config/config.yaml`].

### Delete a job

The reverse of creating a new job: delete the appropriate entries in
[`jobs/config.json`], [`prow/config.yaml`] and [`testgrid/config/config.yaml`].

The [test-infra oncall] must push prow changes (`make -C prow update-config`).

## Building and testing the test-infra

We use [Bazel](https://www.bazel.io/) to build and test the code in this repo.
The commands `bazel build //...` and `bazel test //...` should be all you need
for most cases. If you modify Go code, run `./verify/update-bazel.sh` to keep
`BUILD` files up-to-date.

## Federated Testing

The Kubernetes project encourages organizations to contribute execution of e2e
test jobs for a variety of platforms (e.g., Azure, rktnetes).  The test-history
scripts gather e2e results from these federated jobs.  For information about
how to contribute test results, see [Federated Testing](docs/federated_testing.md).


[`jobs/config.json`]: https://github.com/kubernetes/test-infra/blob/master/jobs/config.json
[`prow/config.yaml`]: https://github.com/kubernetes/test-infra/blob/master/prow/config.yaml
[`testgrid/config/config.yaml`]: https://github.com/kubernetes/test-infra/blob/master/testgrid/config/config.yaml
[test-infra oncall]: https://go.k8s.io/oncall
