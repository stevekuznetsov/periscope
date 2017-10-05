package main

import (
	"flag"

	"github.com/sirupsen/logrus"
	"github.com/stevekuznetsov/periscope/pkg/config/sub"
	"github.com/stevekuznetsov/periscope/pkg/sub/gcs"
)

var (
	configPath = flag.String("config-path", "", "Path to JSON subscription configuration.")
)

func main() {
	flag.Parse()
	logrus.SetFormatter(&logrus.JSONFormatter{})

	config, err := sub.LoadConfiguration(*configPath)
	if err != nil {
		logrus.WithError(err).Fatalf("Failed to load subscription configuration.")
	}

	logger := logrus.StandardLogger()
	if config.GoogleCloudStorage != nil {
		agent := gcs.NewAgent(config.GoogleCloudStorage, logger.WithField("agent", "gcs"))
		logrus.WithError(agent.Run()).Fatalf("Failed to run the GCS agent.")
	}
}
