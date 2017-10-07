package postgresql

// Configuration contains options for connecting
// to a PostgreSQL database in the cluster.
type Configuration struct {
	ServiceName string `json:"service-name"`
	Credentials string `json:"credential-dir"`
}

// Credentials contains the connection credentials
// for a PostgreSQL database.
type Credentials struct {
	ServiceName string
	Database    string
	Username    string
	Password    string
}
