package poll

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
)

func LoadConfiguration(file string) (*Configuration, error) {
	data, err := ioutil.ReadFile(file)
	if err != nil {
		return nil, fmt.Errorf("could not read polling configuration file: %v", err)
	}

	config := &Configuration{}
	if err := json.Unmarshal(data, config); err != nil {
		return nil, fmt.Errorf("could not unmarshal polling configuration: %v", err)
	}

	return config, validate(config)
}

func validate(config *Configuration) error {
	numDrivers := 0

	if config.ProwJob != nil {
		numDrivers += 1
	}

	if numDrivers > 1 {
		return fmt.Errorf("polling configuration had more than one driver set")
	}

	return nil
}
