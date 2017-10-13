package postgresql

import (
	"database/sql"
	"fmt"

	_ "github.com/lib/pq"
	"github.com/sirupsen/logrus"

	"github.com/stevekuznetsov/periscope/pkg/config/postgresql"
	"github.com/stevekuznetsov/periscope/pkg/model"
)

func NewClient(credentials *postgresql.Credentials, logger *logrus.Entry) (*Client, error) {
	connectionString := fmt.Sprintf(
		"host=%s dbname=%s user=%s password=%s sslmode=disable",
		credentials.ServiceName, credentials.Database, credentials.Username, credentials.Password,
	)
	db, err := sql.Open("postgres", connectionString)
	if err != nil {
		return nil, fmt.Errorf("failed to create postgres client: %v", err)
	}

	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to connect to postgres: %v", err)
	}
	logger.Info("Connected to postgresql database")

	return &Client{
		db:          db,
		credentials: credentials,
		logger:      logger,
	}, nil
}

type Client struct {
	db          *sql.DB
	credentials *postgresql.Credentials
	logger      *logrus.Entry
}

// MergeJob will idempotently add the information
// stored in job into the database.
func (c *Client) MergeJob(job *model.Job) error {
	_, err := c.db.Exec(
		`INSERT INTO builds (job, build) VALUES($1, $2) ON CONFLICT DO NOTHING`,
		job.Name,
		job.Build,
	)
	if err != nil {
		return err
	}
}
