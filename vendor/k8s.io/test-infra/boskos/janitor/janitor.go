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
	"os/exec"
	"time"

	"github.com/sirupsen/logrus"
	"k8s.io/test-infra/boskos/client"
	"k8s.io/test-infra/boskos/common"
)

var (
	poolSize       = 100 // Maximum concurrent janitor goroutines TODO(krzyzacy): should remove this limit
	bufferSize     = 1   // Maximum holding resources
	serviceAccount = flag.String("service-account", "", "Path to projects service account")
)

var rTypes common.ResTypes

func init() {
	flag.Var(&rTypes, "resource-type", "comma-separated list of resources need to be cleaned up")
}

func main() {
	logrus.SetFormatter(&logrus.JSONFormatter{})
	boskos := client.NewClient("Janitor", "http://boskos")
	logrus.Info("Initialized boskos client!")

	// Activate service account
	flag.Parse()
	if *serviceAccount == "" {
		logrus.Fatal("--service-account cannot be empty!")
	}

	if len(rTypes) == 0 {
		logrus.Fatal("--resource-type must not be empty!")
	}

	cmd := exec.Command("gcloud", "auth", "activate-service-account", "--key-file="+*serviceAccount)
	if b, err := cmd.CombinedOutput(); err != nil {
		logrus.WithError(err).Fatalf("fail to activate service account from %s :%s", *serviceAccount, string(b))
	}

	buffer := setup(boskos, poolSize, bufferSize, janitorClean)

	for {
		run(boskos, buffer, rTypes)
		time.Sleep(time.Minute)
	}
}

type clean func(string) error

// Clean by janitor script
func janitorClean(proj string) error {
	cmd := exec.Command("/janitor.py", fmt.Sprintf("--project=%s", proj), "--hour=0")
	b, err := cmd.CombinedOutput()
	if err != nil {
		logrus.Infof("janitor.py has some issue: %s", string(b))
	}
	return err
}

type boskosClient interface {
	Acquire(rtype string, state string, dest string) (string, error)
	ReleaseOne(name string, dest string) error
}

func setup(c boskosClient, janitorCount int, bufferSize int, cleanFunc clean) chan string {
	buffer := make(chan string, 1)
	for i := 0; i < janitorCount; i++ {
		go janitor(c, buffer, cleanFunc)
	}
	return buffer
}

func run(c boskosClient, buffer chan string, rtypes []string) int {
	totalAcquire := 0
	res := make(map[string]int)
	for _, s := range rtypes {
		res[s] = 0
	}

	for {
		for r := range res {
			if proj, err := c.Acquire(r, "dirty", "cleaning"); err != nil {
				logrus.WithError(err).Error("boskos acquire failed!")
				totalAcquire += res[r]
				delete(res, r)
			} else if proj == "" {
				totalAcquire += res[r]
				delete(res, r)
			} else {
				buffer <- proj // will block until buffer has a free slot
				res[r]++
			}
		}

		if len(res) == 0 {
			break
		}
	}

	return totalAcquire
}

// async janitor goroutine
func janitor(c boskosClient, buffer chan string, fn clean) {
	for {
		proj := <-buffer

		dest := "free"
		if err := fn(proj); err != nil {
			logrus.WithError(err).Error("janitor.py failed!")
			dest = "dirty"
		}

		if err := c.ReleaseOne(proj, dest); err != nil {
			logrus.WithError(err).Error("boskos release failed!")
		}
	}
}
