package model

import "time"

type JobType string

const (
	JobTypePeriodic   JobType = "periodic"
	JobTypePresubmit          = "presubmit"
	JobTypePostsubmit         = "postsubmit"
	JobTypeBatch              = "batch"
)

type Job struct {
	Name  string `json:"name"`
	Build int    `json:"build"`

	Results *Results `json:"results,omitempty"`
	Source  *Source  `json:"source,omitempty"`
	Pulls   []*Pull  `json:"pulls,omitempty"`

	StorageRefs *StorageRefs `json:"storageRefs,omitempty"`
}

type Results struct {
	Type    JobType    `json:"type"`
	Start   *time.Time `json:"start,omitempty"`
	Finish  *time.Time `json:"finish,omitempty"`
	Success *bool      `json:"success,omitempty"`

	TestResults *TestResults `json:"testResults,omitempty"`
}

type TestResults struct {
	Succeeded int `json:"succeeded"`
	Skipped   int `json:"skipped"`
	Failed    int `json:"failed"`

	FailedTests []*TestDetail `json:"failedTests,omitempty"`
}

type TestDetail struct {
	Name     string        `json:"name"`
	Duration time.Duration `json:"duration"`
	Output   string        `json:"output"`
	Stderr   string        `json:"stderr"`
	Stdout   string        `json:"stdout"`
}

type Source struct {
	Org  string `json:"org"`
	Repo string `json:"repo"`
	Ref  string `json:"ref"`
	Sha  string `json:"Sha"`
}

type Pull struct {
	Id  int    `json:"id"`
	Sha string `json:"Sha"`
}

type StorageRefs struct {
	BaseUrl string `json:"url"`
}
