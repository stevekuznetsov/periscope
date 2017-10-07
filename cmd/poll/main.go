package main

import (
	"flag"

	"time"

	"github.com/sirupsen/logrus"
	"github.com/stevekuznetsov/periscope/pkg/config/poll"
	"github.com/stevekuznetsov/periscope/pkg/poll/prow"
	"github.com/stevekuznetsov/periscope/pkg/config/postgresql"
	postgresql2 "github.com/stevekuznetsov/periscope/pkg/postgresql"
)

var (
	configPath = flag.String("config-path", "", "Path to configuration.")
	psqlConfigPath = flag.String("psql-config-path", "", "Path to PostgreSQL configuration.")
)

func main() {
	flag.Parse()
	logrus.SetFormatter(&logrus.JSONFormatter{})

	config, err := poll.LoadConfiguration(*configPath)
	if err != nil {
		logrus.WithError(err).Fatalf("Failed to load prow configuration.")
	}

	psqlConfig, err := postgresql.LoadCredentials(*psqlConfigPath)
	if err != nil {
		logrus.WithError(err).Fatalf("Failed to load postgresql configuration.")
	}

	logger := logrus.StandardLogger()

	_, err = postgresql2.NewClient(psqlConfig, logger.WithField("agent", "psql"))
	if err != nil {
		logrus.WithError(err).Fatalf("Failed to connect to postgresql.")
	}

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
