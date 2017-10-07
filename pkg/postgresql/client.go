package postgresql

import (
	"database/sql"
	"fmt"

	_ "github.com/lib/pq"
	"github.com/sirupsen/logrus"

	"github.com/stevekuznetsov/periscope/pkg/config/postgresql"
)

func NewClient(credentials *postgresql.Credentials, logger *logrus.Entry) (*Client, error) {
	connectionString := fmt.Sprintf(
		"host=%s dbname=%s user=%s password=%s",
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
