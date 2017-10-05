package sub

// Configuration contains options for subscription
// to cloud storage notifications. Only one of the
// driver configurations should be non-empty.
type Configuration struct {
	GoogleCloudStorage *GoogleCloudStorage `json:"gcs,omitempty"`
}

// GoogleCloudStorage contains options for receiving
// notifications from a GCS bucket subscription.
type GoogleCloudStorage struct {
	ProjectIdentifier string `json:"project-id"`
	Topic             string `json:"topic"`

	// CredentialsFile is the file where Google Cloud
	// authentication credentials are stored. See:
	// https://developers.google.com/identity/protocols/OAuth2ServiceAccount
	CredentialsFile string `json:"credentials-file"`
}
