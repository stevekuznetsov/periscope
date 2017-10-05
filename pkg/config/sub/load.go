package sub

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
)

func LoadConfiguration(file string) (*Configuration, error) {
	data, err := ioutil.ReadFile(file)
	if err != nil {
		return nil, fmt.Errorf("could not read subscription configuration file: %v", err)
	}

	config := &Configuration{}
	if err := json.Unmarshal(data, config); err != nil {
		return nil, fmt.Errorf("could not unmarshal subscription configuration: %v", err)
	}

	return config, validate(config)
}

func validate(config *Configuration) error {
	numDrivers := 0

	if config.GoogleCloudStorage != nil {
		numDrivers += 1
	}

	if numDrivers > 1 {
		return fmt.Errorf("subscription configuration had more than one driver set")
	}

	return nil
}
