all: builds deployments
.PHONY: all

builds: env-build sub-build
.PHONY: builds

env-build:
    oc process -f openshift/env-build.yaml | oc apply -f -
.PHONY: env-build

sub-build:
    oc process -f openshift/sub-build.yaml | oc apply -f -
.PHONY: sub-build

deployments: sub-deployment poll-deployment psql-deployment
.PHONY: deployments

sub-deployment:
    oc create secret generic gce --from-file=credentials=${GCE_CREDENTIALS_FILE}
    oc create configmap sub-config --from-file=config=config/sub.json -o yaml --dry-run | oc apply -f -
    oc apply -f openshift/sub-deployment.yaml
.PHONY: sub-deployment

poll-deployment:
    oc create configmap poll-config --from-file=config=config/poll.json -o yaml --dry-run | oc apply -f -
    oc apply -f openshift/poll-deployment.yaml
.PHONY: sub-deployment

psql-deployment:
    oc create configmap psql-schema --from-file=schema.sql=postgresql/schema.sql -o yaml --dry-run | oc apply -f -
    oc process -f openshift/psql-deployment.yaml | oc apply -f -
.PHONY: sub-deployment