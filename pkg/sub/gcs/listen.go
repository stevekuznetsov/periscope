package gcs

import (
	"fmt"

	"cloud.google.com/go/pubsub"
	"github.com/sirupsen/logrus"
	"golang.org/x/net/context"
	"google.golang.org/api/option"

	"github.com/stevekuznetsov/periscope/pkg/config/sub"
)

const (
	subscriptionName = "periscope-gcp-listener"
)

func NewAgent(subConfig *sub.GoogleCloudStorage, logger *logrus.Entry) *Agent {
	return &Agent{
		subConfig: subConfig,
		logger:    logger,
	}
}

type Agent struct {
	subConfig *sub.GoogleCloudStorage
	logger    *logrus.Entry
}

func (a *Agent) Run() error {
	ctx := context.Background()

	client, err := pubsub.NewClient(ctx, a.subConfig.ProjectIdentifier, option.WithCredentialsFile(a.subConfig.CredentialsFile))
	if err != nil {
		return fmt.Errorf("failed to get a client: %v", err)
	}
	defer client.Close()
	a.logger.Infof("created a GCP pub/sub client for project %q", a.subConfig.ProjectIdentifier)

	topics := client.Topics(ctx)
	for {
		topic, err := topics.Next()
		if err != nil {
			a.logger.WithError(err).Infof("Failed to get next topic")
		}
		a.logger.Infof("Found topic %q", topic.ID())
	}

	topic := client.Topic(a.subConfig.Topic)
	a.logger.Infof("created a GCP pub/sub topic for %q", topic.ID())

	subscription, err := client.CreateSubscription(ctx, subscriptionName, pubsub.SubscriptionConfig{Topic: topic})
	if err != nil {
		return fmt.Errorf("failed to get a subscription: %v", err)
	}
	a.logger.Infof("subscribed to GCP pub/sub topic as %q", subscription.ID())

	if err := subscription.Receive(ctx, a.handle); err != nil {
		return fmt.Errorf("failed to receive message: %v", err)
	}

	return nil
}

func (a *Agent) handle(ctx context.Context, message *pubsub.Message) {
	a.logger.WithField("id", message.ID).WithField("attributes", message.Attributes).Infof("Recieved: %v", message.Data)
	message.Ack()
}
