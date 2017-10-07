package postgresql

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"path"
)

const (
	databaseNamePath     string = "database-name"
	databaseUserPath            = "database-user"
	databasePasswordPath        = "database-password"
)

func LoadCredentials(file string) (*Credentials, error) {
	data, err := ioutil.ReadFile(file)
	if err != nil {
		return nil, fmt.Errorf("could not read postgresql configuration file: %v", err)
	}

	config := &Configuration{}
	if err := json.Unmarshal(data, config); err != nil {
		return nil, fmt.Errorf("could not unmarshal postgresql  configuration: %v", err)
	}

	database, err := ioutil.ReadFile(path.Join(config.Credentials, databaseNamePath))
	if err != nil {
		return nil, fmt.Errorf("could not read database name: %v", err)
	}

	username, err := ioutil.ReadFile(path.Join(config.Credentials, databaseUserPath))
	if err != nil {
		return nil, fmt.Errorf("could not read database user: %v", err)
	}

	password, err := ioutil.ReadFile(path.Join(config.Credentials, databasePasswordPath))
	if err != nil {
		return nil, fmt.Errorf("could not read database password: %v", err)
	}

	return &Credentials{
		ServiceName: config.ServiceName,
		Database:    string(database),
		Username:    string(username),
		Password:    string(password),
	}, nil
}
