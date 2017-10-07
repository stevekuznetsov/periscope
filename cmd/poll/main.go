package main

import (
	"flag"

	"time"

	"github.com/sirupsen/logrus"
	"github.com/stevekuznetsov/periscope/pkg/config/poll"
	"github.com/stevekuznetsov/periscope/pkg/poll/prow"
)

var (
	configPath = flag.String("config-path", "", "Path to JSON subscription configuration.")
)

func main() {
	flag.Parse()
	logrus.SetFormatter(&logrus.JSONFormatter{})

	config, err := poll.LoadConfiguration(*configPath)
	if err != nil {
		logrus.WithError(err).Fatalf("Failed to load subscription configuration.")
	}

	logger := logrus.StandardLogger()
	if config.ProwJob != nil {
		agent := prow.NewAgent(config.ProwJob, logger.WithField("agent", "prow"))
		for range time.Tick(30 * time.Second) {
			err := agent.Run()
			if err != nil {
				logrus.WithError(err).Error("Failed to run the prow agent.")
			}
		}
	}
}
