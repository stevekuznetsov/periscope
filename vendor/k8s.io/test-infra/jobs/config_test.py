#!/usr/bin/env python

# Copyright 2017 The Kubernetes Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for config.json and Prow configuration."""


import unittest

import collections
import json
import os
import re

import config_sort
import env_gc
import yaml

# pylint: disable=too-many-public-methods, too-many-branches, too-many-locals, too-many-statements

def get_required_jobs():
    required_jobs = set()
    configs_dir = config_sort.test_infra('mungegithub', 'submit-queue', 'deployment')
    for root, _, files in os.walk(configs_dir):
        for file_name in files:
            if file_name == 'configmap.yaml':
                path = os.path.join(root, file_name)
                with open(path) as fp:
                    conf = yaml.safe_load(fp)
                    for job in conf.get('required-retest-contexts', '').split(','):
                        if job:
                            required_jobs.add(job)
    return required_jobs

class JobTest(unittest.TestCase):

    excludes = [
        'BUILD',  # For bazel
        'config.json',  # For --json mode
        'validOwners.json', # Contains a list of current sigs; sigs are allowed to own jobs
        'config_sort.py', # Tool script to sort config.json
        'config_test.py', # Script for testing config.json and Prow config.
        'env_gc.py', # Tool script to garbage collect unused .env files.
        'move_extract.py',
        # Node-e2e image configurations
        'benchmark-config.yaml',
        'image-config.yaml',
        'image-config-serial.yaml',
    ]
    # also exclude .pyc
    excludes.extend(e + 'c' for e in excludes if e.endswith('.py'))

    yaml_suffix = {
        'jenkins/job-configs/bootstrap-maintenance.yaml' : 'suffix',
        'jenkins/job-configs/kubernetes-jenkins-pull/bootstrap-pull-json.yaml' : 'jsonsuffix',
        'jenkins/job-configs/kubernetes-jenkins-pull/bootstrap-security-pull.yaml' : 'suffix',
        'jenkins/job-configs/kubernetes-jenkins/bootstrap-ci.yaml' : 'suffix',
        'jenkins/job-configs/kubernetes-jenkins/bootstrap-ci-commit.yaml' : 'commit-suffix',
        'jenkins/job-configs/kubernetes-jenkins/bootstrap-ci-repo.yaml' : 'repo-suffix',
        'jenkins/job-configs/kubernetes-jenkins/bootstrap-ci-soak.yaml' : 'soak-suffix',
        'jenkins/job-configs/kubernetes-jenkins/bootstrap-ci-dockerpush.yaml' : 'dockerpush-suffix'
    }

    prow_config = '../prow/config.yaml'

    realjobs = {}
    prowjobs = []
    presubmits = []

    @property
    def jobs(self):
        """[(job, job_path)] sequence"""
        for path, _, filenames in os.walk(config_sort.test_infra('jobs')):
            for job in [f for f in filenames if f not in self.excludes]:
                job_path = os.path.join(path, job)
                yield job, job_path

    def test_config_is_sorted(self):
        """Test jobs/config.json, prow/config.yaml and boskos/resources.json are sorted."""
        with open(config_sort.test_infra('jobs/config.json')) as fp:
            original = fp.read()
            expect = config_sort.sorted_job_config().getvalue()
            if original != expect:
                self.fail('jobs/config.json is not sorted, please run '
                          '`bazel run //jobs:config_sort`')
        with open(config_sort.test_infra('prow/config.yaml')) as fp:
            original = fp.read()
            expect = config_sort.sorted_prow_config().getvalue()
            if original != expect:
                self.fail('prow/config.yaml is not sorted, please run '
                          '`bazel run //jobs:config_sort`')
        with open(config_sort.test_infra('boskos/resources.json')) as fp:
            original = fp.read()
            expect = config_sort.sorted_boskos_config().getvalue()
            if original != expect:
                self.fail('boskos/resources.json is not sorted, please run '
                          '`bazel run //jobs:config_sort`')

    def test_orphaned_env(self):
        orphans = env_gc.find_orphans()
        if orphans:
            self.fail('the following .env files are not referenced ' +
                      'in config.json, please run `bazel run //jobs:env_gc: ' +
                      ' '.join(orphans))

    def test_bootstrap_maintenance_yaml(self):
        def check(job, name):
            job_name = 'maintenance-%s' % name
            self.assertIn('frequency', job)
            self.assertIn('repo-name', job)
            self.assertIn('.', job['repo-name'])  # Has domain
            self.assertGreater(job['timeout'], 0)
            return job_name

        self.check_bootstrap_yaml('jenkins/job-configs/bootstrap-maintenance.yaml', check)

    def test_bootstrap_pull_json_yaml(self):
        def check(job, name):
            job_name = 'pull-%s' % name
            self.assertIn('max-total', job)
            self.assertIn('repo-name', job)
            self.assertIn('.', job['repo-name'])  # Has domain
            self.assertIn('timeout', job)
            self.assertNotIn('json', job)
            self.assertGreater(job['timeout'], 0)
            return job_name

        self.check_bootstrap_yaml(
            'jenkins/job-configs/kubernetes-jenkins-pull/bootstrap-pull-json.yaml', check)

    def test_bootstrap_security_pull(self):
        def check(job, name):
            job_name = 'pull-%s' % name
            self.assertIn('max-total', job)
            self.assertIn('repo-name', job)
            self.assertIn('.', job['repo-name'])  # Has domain
            self.assertIn('timeout', job)
            self.assertNotIn('json', job)
            self.assertGreater(job['timeout'], 0)
            return job_name

        self.check_bootstrap_yaml(
            'jenkins/job-configs/kubernetes-jenkins-pull/bootstrap-security-pull.yaml', check)

    def test_bootstrap_security_match(self):
        json_jobs = self.load_bootstrap_yaml(
            'jenkins/job-configs/kubernetes-jenkins-pull/bootstrap-pull-json.yaml')

        sec_jobs = self.load_bootstrap_yaml(
            'jenkins/job-configs/kubernetes-jenkins-pull/bootstrap-security-pull.yaml')
        for name, job in sec_jobs.iteritems():
            self.assertIn(name, json_jobs)
            job2 = json_jobs[name]
            for attr in job:
                if attr == 'repo-name':
                    continue
                self.assertEquals(job[attr], job2[attr])


    def test_bootstrap_ci_yaml(self):
        def check(job, name):
            job_name = 'ci-%s' % name
            self.assertIn('frequency', job)
            self.assertIn('trigger-job', job)
            self.assertNotIn('branch', job)
            self.assertNotIn('json', job)
            self.assertGreater(job['timeout'], 0, job_name)
            self.assertGreaterEqual(job['jenkins-timeout'], job['timeout']+100, job_name)
            return job_name

        self.check_bootstrap_yaml(
            'jenkins/job-configs/kubernetes-jenkins/bootstrap-ci.yaml',
            check)

    def test_bootstrap_ci_commit_yaml(self):
        def check(job, name):
            job_name = 'ci-%s' % name
            self.assertIn('branch', job)
            self.assertIn('commit-frequency', job)
            self.assertIn('giturl', job)
            self.assertIn('repo-name', job)
            self.assertIn('timeout', job)
            self.assertNotIn('use-logexporter', job)
            self.assertGreater(job['timeout'], 0, job)

            return job_name

        self.check_bootstrap_yaml(
            'jenkins/job-configs/kubernetes-jenkins/bootstrap-ci-commit.yaml',
            check)

    def test_bootstrap_ci_repo_yaml(self):
        def check(job, name):
            job_name = 'ci-%s' % name
            self.assertIn('branch', job)
            self.assertIn('frequency', job)
            self.assertIn('repo-name', job)
            self.assertIn('timeout', job)
            self.assertNotIn('json', job)
            self.assertNotIn('use-logexporter', job)
            self.assertGreater(job['timeout'], 0, name)
            return job_name

        self.check_bootstrap_yaml(
            'jenkins/job-configs/kubernetes-jenkins/bootstrap-ci-repo.yaml',
            check)

    def test_bootstrap_ci_soak_yaml(self):
        def check(job, name):
            job_name = 'ci-%s' % name
            self.assertIn('blocker', job)
            self.assertIn('frequency', job)
            self.assertIn('scan', job)
            self.assertNotIn('repo-name', job)
            self.assertNotIn('branch', job)
            self.assertIn('timeout', job)
            self.assertIn('soak-repos', job)
            self.assertNotIn('use-logexporter', job)
            self.assertGreater(job['timeout'], 0, name)

            return job_name

        self.check_bootstrap_yaml(
            'jenkins/job-configs/kubernetes-jenkins/bootstrap-ci-soak.yaml',
            check)

    def test_bootstrap_ci_dockerpush(self):
        def check(job, name):
            job_name = 'ci-%s' % name
            self.assertIn('branch', job)
            self.assertIn('frequency', job)
            self.assertIn('repo-name', job)
            self.assertIn('timeout', job)
            self.assertNotIn('use-logexporter', job)
            self.assertGreater(job['timeout'], 0, name)
            return job_name

        self.check_bootstrap_yaml(
            'jenkins/job-configs/kubernetes-jenkins/bootstrap-ci-dockerpush.yaml',
            check)

    def check_job_template(self, tmpl):
        builders = tmpl.get('builders')
        if not isinstance(builders, list):
            self.fail(tmpl)
        self.assertEquals(1, len(builders), builders)
        shell = builders[0]
        if not isinstance(shell, dict):
            self.fail(tmpl)
        self.assertEquals(1, len(shell), tmpl)
        if 'raw' in shell:
            self.assertEquals('maintenance-all-{suffix}', tmpl['name'])
            return
        cmd = shell.get('shell')
        if not isinstance(cmd, basestring):
            self.fail(tmpl)
        self.assertIn('--service-account=', cmd)
        self.assertIn('--upload=', cmd)
        if 'kubernetes-security' in cmd:
            self.assertIn('--upload=\'gs://kubernetes-security-jenkins/pr-logs\'', cmd)
        elif '${{PULL_REFS}}' in cmd:
            self.assertIn('--upload=\'gs://kubernetes-jenkins/pr-logs\'', cmd)
        else:
            self.assertIn('--upload=\'gs://kubernetes-jenkins/logs\'', cmd)

    def add_prow_job(self, job):
        name = job.get('name')
        real_job = {}
        real_job['name'] = name
        if 'spec' in job:
            spec = job.get('spec')
            for container in spec.get('containers'):
                if 'args' in container:
                    for arg in container.get('args'):
                        match = re.match(r'--timeout=(\d+)', arg)
                        if match:
                            real_job['timeout'] = match.group(1)
        if 'pull-' not in name and name in self.realjobs and name not in self.prowjobs:
            self.fail('CI job %s exist in both Jenkins and Prow config!' % name)
        if name not in self.realjobs:
            self.realjobs[name] = real_job
            self.prowjobs.append(name)
        if 'run_after_success' in job:
            for sub in job.get('run_after_success'):
                self.add_prow_job(sub)

    def load_prow_yaml(self, path):
        with open(os.path.join(
            os.path.dirname(__file__), path)) as fp:
            doc = yaml.safe_load(fp)

        if 'periodics' not in doc:
            self.fail('No periodics in prow config!')

        if 'presubmits' not in doc:
            self.fail('No presubmits in prow config!')

        for item in doc.get('periodics'):
            self.add_prow_job(item)

        if 'postsubmits' not in doc:
            self.fail('No postsubmits in prow config!')

        self.presubmits = doc.get('presubmits')
        postsubmits = doc.get('postsubmits')

        for _repo, joblist in self.presubmits.items() + postsubmits.items():
            for job in joblist:
                self.add_prow_job(job)

    def load_bootstrap_yaml(self, path):
        with open(config_sort.test_infra(path)) as fp:
            doc = yaml.safe_load(fp)

        project = None
        defined_templates = set()
        for item in doc:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get('job-template'), dict):
                defined_templates.add(item['job-template']['name'])
                self.check_job_template(item['job-template'])
            if not isinstance(item.get('project'), dict):
                continue
            project = item['project']
            self.assertIn('bootstrap-', project.get('name'))
            break
        else:
            self.fail('Could not find bootstrap-pull-jobs project')

        self.assertIn('jobs', project)
        used_templates = {j for j in project['jobs']}
        msg = '\nMissing templates: %s\nUnused templates: %s' % (
            ','.join(used_templates - defined_templates),
            ','.join(defined_templates - used_templates))
        self.assertEquals(defined_templates, used_templates, msg)

        self.assertIn(path, self.yaml_suffix)
        jobs = project.get(self.yaml_suffix[path])
        if not jobs or not isinstance(jobs, list):
            self.fail('Could not find suffix list in %s' % (project))

        real_jobs = {}
        for job in jobs:
            # Things to check on all bootstrap jobs
            if not isinstance(job, dict):
                self.fail('suffix items should be dicts: %s' % jobs)
            self.assertEquals(1, len(job), job)
            name = job.keys()[0]
            real_job = job[name]
            self.assertNotIn(name, real_jobs, 'duplicate job: %s' % name)
            real_jobs[name] = real_job
            real_name = real_job.get('job-name', 'unset-%s' % name)
            if real_name not in self.realjobs:
                self.realjobs[real_name] = real_job
        return real_jobs

    def check_bootstrap_yaml(self, path, check):
        for name, real_job in self.load_bootstrap_yaml(path).iteritems():
            # Things to check on all bootstrap jobs

            for key, value in real_job.items():
                if not isinstance(value, (basestring, int)):
                    self.fail('Jobs may not contain child objects %s: %s' % (
                        key, value))
                if '{' in str(value):
                    self.fail('Jobs may not contain {expansions} - %s: %s' % (
                        key, value))  # Use simple strings
            # Things to check on specific flavors.
            job_name = check(real_job, name)
            self.assertTrue(job_name)
            self.assertEquals(job_name, real_job.get('job-name'))

    def get_real_bootstrap_job(self, job):
        key = os.path.splitext(job.strip())[0]
        if not key in self.realjobs:
            for yamlf in self.yaml_suffix:
                self.load_bootstrap_yaml(yamlf)
            self.load_prow_yaml(self.prow_config)
        self.assertIn(key, sorted(self.realjobs))  # sorted for clearer error message
        return self.realjobs.get(key)

    def test_non_blocking_jenkins(self):
        """All PR non-blocking jenkins jobs are always_run: false"""
        # ref https://github.com/kubernetes/test-infra/issues/4637
        if not self.presubmits:
            self.load_prow_yaml(self.prow_config)
        required_jobs = get_required_jobs()
        # TODO(bentheelder): should we also include other repos?
        # If we do, we need to check which ones have a deployment in get_required_jobs
        # and ignore the ones without submit-queue deployments. This seems brittle
        # and unnecessary for now though.
        for job in self.presubmits.get('kubernetes/kubernetes', []):
            if (job['agent'] == 'jenkins' and
                    job['name'] not in required_jobs and
                    job.get('always_run', False)):
                self.fail(
                    'Jenkins jobs should not be `always_run: true`'
                    ' unless they are required! %s'
                    % job['name'])

    def test_valid_timeout(self):
        """All jobs set a timeout less than 120m or set DOCKER_TIMEOUT."""
        default_timeout = 60
        bad_jobs = set()
        with open(config_sort.test_infra('jobs/config.json')) as fp:
            config = json.loads(fp.read())

        for job, job_path in self.jobs:
            job_name = job.rsplit('.', 1)[0]
            modern = config.get(job_name, {}).get('scenario') in [
                'kubernetes_e2e',
                'kubernetes_kops_aws',
            ]
            valids = [
                'kubernetes-e2e-',
                'kubernetes-kubemark-',
                'kubernetes-soak-',
                'kubernetes-federation-e2e-',
                'kops-e2e-',
            ]

            if not re.search('|'.join(valids), job):
                continue
            with open(job_path) as fp:
                lines = list(l for l in fp if not l.startswith('#'))
            container_timeout = default_timeout
            kubetest_timeout = None
            for line in lines:  # Validate old pattern no longer used
                if line.startswith('### Reporting'):
                    bad_jobs.add(job)
                if '{rc}' in line:
                    bad_jobs.add(job)
            self.assertFalse(job.endswith('.sh'), job)
            self.assertTrue(modern, job)

            realjob = self.get_real_bootstrap_job(job)
            self.assertTrue(realjob)
            self.assertIn('timeout', realjob, job)
            container_timeout = int(realjob['timeout'])
            for line in lines:
                if 'DOCKER_TIMEOUT=' in line:
                    self.fail('Set container timeout in prow and/or bootstrap yaml: %s' % job)
                if 'KUBEKINS_TIMEOUT=' in line:
                    self.fail(
                        'Set kubetest --timeout in config.json, not KUBEKINS_TIMEOUT: %s'
                        % job
                    )
            for arg in config[job_name]['args']:
                if arg == '--timeout=None':
                    bad_jobs.add(('Must specify a timeout', job, arg))
                mat = re.match(r'--timeout=(\d+)m', arg)
                if not mat:
                    continue
                kubetest_timeout = int(mat.group(1))
            if kubetest_timeout is None:
                self.fail('Missing timeout: %s' % job)
            if kubetest_timeout > container_timeout:
                bad_jobs.add((job, kubetest_timeout, container_timeout))
            elif kubetest_timeout + 20 > container_timeout:
                bad_jobs.add((
                    'insufficient kubetest leeway',
                    job, kubetest_timeout, container_timeout
                    ))
        if bad_jobs:
            self.fail(
                'jobs: %s, '
                'prow timeout need to be at least 20min longer than timeout in config.json'
                % ('\n'.join(str(s) for s in bad_jobs))
                )

    def test_valid_job_config_json(self):
        """Validate jobs/config.json."""
        # bootstrap integration test scripts
        ignore = [
            'fake-failure',
            'fake-branch',
            'fake-pr',
            'random_job',
        ]

        self.load_prow_yaml(self.prow_config)
        config = config_sort.test_infra('jobs/config.json')
        owners = config_sort.test_infra('jobs/validOwners.json')
        with open(config) as fp, open(owners) as ownfp:
            config = json.loads(fp.read())
            valid_owners = json.loads(ownfp.read())
            for job in config:
                if job not in ignore:
                    self.assertTrue(job in self.prowjobs or job in self.realjobs,
                                    '%s must have a matching jenkins/prow entry' % job)

                # onwership assertions
                self.assertIn('sigOwners', config[job], job)
                self.assertIsInstance(config[job]['sigOwners'], list, job)
                self.assertTrue(config[job]['sigOwners'], job) # non-empty
                owners = config[job]['sigOwners']
                for owner in owners:
                    self.assertIsInstance(owner, basestring, job)
                    self.assertIn(owner, valid_owners, job)

                # env assertions
                self.assertTrue('scenario' in config[job], job)
                scenario = config_sort.test_infra('scenarios/%s.py' % config[job]['scenario'])
                self.assertTrue(os.path.isfile(scenario), job)
                self.assertTrue(os.access(scenario, os.X_OK|os.R_OK), job)
                args = config[job].get('args', [])
                use_shared_build_in_args = False
                extract_in_args = False
                build_in_args = False
                for arg in args:
                    if arg.startswith('--use-shared-build'):
                        use_shared_build_in_args = True
                    elif arg.startswith('--build'):
                        build_in_args = True
                    elif arg.startswith('--extract'):
                        extract_in_args = True
                    match = re.match(r'--env-file=([^\"]+)\.env', arg)
                    if match:
                        env_path = match.group(1)
                        self.assertTrue(env_path.startswith('jobs/'), env_path)
                        path = config_sort.test_infra('%s.env' % env_path)
                        self.assertTrue(
                            os.path.isfile(path),
                            '%s does not exist for %s' % (path, job))
                    elif 'kops' not in job:
                        match = re.match(r'--cluster=([^\"]+)', arg)
                        if match:
                            cluster = match.group(1)
                            self.assertLessEqual(
                                len(cluster), 23,
                                'Job %r, --cluster should be 23 chars or fewer' % job
                                )
                # these args should not be combined:
                # --use-shared-build and (--build or --extract)
                self.assertFalse(use_shared_build_in_args and build_in_args)
                self.assertFalse(use_shared_build_in_args and extract_in_args)
                if config[job]['scenario'] == 'kubernetes_e2e':
                    if job in self.prowjobs:
                        for arg in args:
                            # --mode=local is default now
                            self.assertNotIn('--mode', arg, job)
                    else:
                        self.assertIn('--mode=docker', args, job)
                    for arg in args:
                        if "--env=" in arg:
                            self._check_env(job, arg.split("=", 1)[1])
                    if '--provider=gke' in args:
                        self.assertTrue('--deployment=gke' in args,
                                        '%s must use --deployment=gke' % job)
                        self.assertFalse(any('--gcp-master-image' in a for a in args),
                                         '%s cannot use --gcp-master-image on GKE' % job)
                        self.assertFalse(any('--gcp-nodes' in a for a in args),
                                         '%s cannot use --gcp-nodes on GKE' % job)
                    if '--deployment=gke' in args:
                        self.assertTrue(any('--gcp-node-image' in a for a in args), job)
                    self.assertNotIn('--charts-tests', args)  # Use --charts
                    if any('--check_version_skew' in a for a in args):
                        self.fail('Use --check-version-skew, not --check_version_skew in %s' % job)
                    if '--check-leaked-resources=true' in args:
                        self.fail('Use --check-leaked-resources (no value) in %s' % job)
                    if '--check-leaked-resources==false' in args:
                        self.fail(
                            'Remove --check-leaked-resources=false (default value) from %s' % job)
                    if (
                            '--env-file=jobs/pull-kubernetes-e2e.env' in args
                            and '--check-leaked-resources' in args):
                        self.fail('PR job %s should not check for resource leaks' % job)
                    # Consider deleting any job with --check-leaked-resources=false
                    if (
                            '--provider=gce' not in args
                            and '--provider=gke' not in args
                            and '--check-leaked-resources' in args
                            and 'generated' not in config[job].get('tags', [])):
                        self.fail('Only GCP jobs can --check-leaked-resources, not %s' % job)
                    if '--mode=local' in args:
                        self.fail('--mode=local is default now, drop that for %s' % job)

                    extracts = [a for a in args if '--extract=' in a]
                    shared_builds = [a for a in args if '--use-shared-build' in a]
                    node_e2e = [a for a in args if '--deployment=node' in a]
                    pull = job.startswith('pull-')
                    if shared_builds and extracts:
                        self.fail(('e2e jobs cannot have --use-shared-build'
                                   ' and --extract: %s %s') % (job, args))
                    elif not extracts and not shared_builds and not node_e2e:
                        self.fail(('e2e job needs --extract or'
                                   ' --use-shared-build: %s %s') % (job, args))

                    if shared_builds or node_e2e and not pull:
                        expected = 0
                    elif any(s in job for s in [
                            'upgrade', 'skew', 'downgrade', 'rollback',
                            'ci-kubernetes-e2e-gce-canary',
                    ]):
                        expected = 2
                    else:
                        expected = 1
                    if len(extracts) != expected:
                        self.fail('Wrong number of --extract args (%d != %d) in %s' % (
                            len(extracts), expected, job))

                    has_image_family = any(
                        [x for x in args if x.startswith('--image-family')])
                    has_image_project = any(
                        [x for x in args if x.startswith('--image-project')])
                    docker_mode = any(
                        [x for x in args if x.startswith('--mode=docker')])
                    if (
                            (has_image_family or has_image_project)
                            and docker_mode):
                        self.fail('--image-family / --image-project is not '
                                  'supported in docker mode: %s' % job)
                    if has_image_family != has_image_project:
                        self.fail('--image-family and --image-project must be'
                                  'both set or unset: %s' % job)

                    if job.startswith('pull-kubernetes-'):
                        if not 'pull-kubernetes-federation-e2e-gce' in job:
                            # pull-kubernetes-federation-e2e-gce job uses a specific cluster names
                            # instead of dynamic cluster names.
                            self.assertIn('--cluster=', args)
                        if 'gke' in job:
                            stage = 'gs://kubernetes-release-dev/ci'
                            suffix = True
                        elif 'kubeadm' in job:
                            # kubeadm-based jobs use out-of-band .deb artifacts,
                            # not the --stage flag.
                            continue
                        else:
                            stage = 'gs://kubernetes-release-pull/ci/%s' % job
                            suffix = False
                        if not shared_builds:
                            self.assertIn('--stage=%s' % stage, args)
                        self.assertEquals(
                            suffix,
                            any('--stage-suffix=' in a for a in args),
                            ('--stage-suffix=', suffix, job, args))


    def test_valid_env(self):
        for job, job_path in self.jobs:
            with open(job_path) as fp:
                data = fp.read()
            if 'kops' in job:  # TODO(fejta): update this one too
                continue
            self.assertNotIn(
                'JENKINS_USE_LOCAL_BINARIES=',
                data,
                'Send --extract=local to config.json, not JENKINS_USE_LOCAL_BINARIES in %s' % job)
            self.assertNotIn(
                'JENKINS_USE_EXISTING_BINARIES=',
                data,
                'Send --extract=local to config.json, not JENKINS_USE_EXISTING_BINARIES in %s' % job)  # pylint: disable=line-too-long

    def test_only_jobs(self):
        """Ensure that everything in jobs/ is a valid job name and script."""
        for job, job_path in self.jobs:
            # Jobs should have simple names: letters, numbers, -, .
            self.assertTrue(re.match(r'[.0-9a-z-_]+.env', job), job)
            # Jobs should point to a real, executable file
            # Note: it is easy to forget to chmod +x
            self.assertTrue(os.path.isfile(job_path), job_path)
            self.assertFalse(os.path.islink(job_path), job_path)
            self.assertTrue(os.access(job_path, os.R_OK), job_path)

    def test_all_project_are_unique(self):
        # pylint: disable=line-too-long
        allowed_list = {
            # The cos image validation jobs intentionally share projects.
            'ci-kubernetes-e2e-gce-cosdev-k8sdev-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosdev-k8sdev-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosdev-k8sdev-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosdev-k8sstable1-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosdev-k8sstable1-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosdev-k8sstable1-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosdev-k8sbeta-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosdev-k8sbeta-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosdev-k8sbeta-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sdev-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sdev-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sdev-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sbeta-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sbeta-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sbeta-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sstable1-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sstable1-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sstable1-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sstable2-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sstable2-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sstable2-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sstable3-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sstable3-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosbeta-k8sstable3-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sdev-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sdev-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sdev-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sbeta-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sbeta-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sbeta-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sstable1-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sstable1-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sstable1-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sstable2-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sstable2-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sstable2-slow': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sstable3-default': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sstable3-serial': 'ci-kubernetes-e2e-gce-cos*',
            'ci-kubernetes-e2e-gce-cosstable1-k8sstable3-slow': 'ci-kubernetes-e2e-gce-cos*',

            # The ubuntu image validation jobs intentionally share projects.
            'ci-kubernetes-e2e-gce-ubuntudev-k8sdev-default': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntudev-k8sdev-serial': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntudev-k8sdev-slow': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntudev-k8sbeta-default': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntudev-k8sbeta-serial': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntudev-k8sbeta-slow': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntudev-k8sstable1-default': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntudev-k8sstable1-serial': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntudev-k8sstable1-slow': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntustable1-k8sdev-default': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntustable1-k8sdev-serial': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntustable1-k8sdev-slow': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntustable1-k8sstable1-default': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntustable1-k8sstable1-serial': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntustable1-k8sstable1-slow': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntustable1-k8sstable2-default': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntustable1-k8sstable2-serial': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gce-ubuntustable1-k8sstable2-slow': 'ci-kubernetes-e2e-gce-ubuntu*',
            'ci-kubernetes-e2e-gke-ubuntustable1-k8sstable1-alphafeatures': 'ci-kubernetes-e2e-gke-ubuntu*',
            'ci-kubernetes-e2e-gke-ubuntustable1-k8sstable1-autoscaling': 'ci-kubernetes-e2e-gke-ubuntu*',
            'ci-kubernetes-e2e-gke-ubuntustable1-k8sstable1-default': 'ci-kubernetes-e2e-gke-ubuntu*',
            'ci-kubernetes-e2e-gke-ubuntustable1-k8sstable1-flaky': 'ci-kubernetes-e2e-gke-ubuntu*',
            'ci-kubernetes-e2e-gke-ubuntustable1-k8sstable1-ingress': 'ci-kubernetes-e2e-gke-ubuntu*',
            'ci-kubernetes-e2e-gke-ubuntustable1-k8sstable1-reboot': 'ci-kubernetes-e2e-gke-ubuntu*',
            'ci-kubernetes-e2e-gke-ubuntustable1-k8sstable1-serial': 'ci-kubernetes-e2e-gke-ubuntu*',
            'ci-kubernetes-e2e-gke-ubuntustable1-k8sstable1-slow': 'ci-kubernetes-e2e-gke-ubuntu*',
            'ci-kubernetes-e2e-gke-ubuntustable1-k8sstable1-updown': 'ci-kubernetes-e2e-gke-ubuntu*',
            # The 1.5 and 1.6 scalability jobs intentionally share projects.
            'ci-kubernetes-e2e-gci-gce-scalability-release-1-7': 'ci-kubernetes-e2e-gci-gce-scalability-release-*',
            'ci-kubernetes-e2e-gci-gce-scalability-stable1': 'ci-kubernetes-e2e-gci-gce-scalability-release-*',
            'ci-kubernetes-e2e-gce-scalability': 'ci-kubernetes-e2e-gce-scalability-*',
            'ci-kubernetes-e2e-gce-scalability-canary': 'ci-kubernetes-e2e-gce-scalability-*',
            # TODO(fejta): remove these (found while migrating jobs)
            'ci-kubernetes-kubemark-100-gce': 'ci-kubernetes-kubemark-*',
            'ci-kubernetes-kubemark-5-gce': 'ci-kubernetes-kubemark-*',
            'ci-kubernetes-kubemark-5-gce-last-release': 'ci-kubernetes-kubemark-*',
            'ci-kubernetes-kubemark-high-density-100-gce': 'ci-kubernetes-kubemark-*',
            'ci-kubernetes-kubemark-gce-scale': 'ci-kubernetes-scale-*',
            'pull-kubernetes-kubemark-e2e-gce-big': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gce-large-manual-up': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gce-large-manual-down': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gce-large-correctness': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gce-large-performance': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gce-scale-correctness': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gce-scale-performance': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gke-large-correctness': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gke-large-performance': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gke-large-deploy': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gke-large-teardown': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gke-scale-correctness': 'ci-kubernetes-scale-*',
            'ci-kubernetes-e2e-gce-federation': 'ci-kubernetes-federation-*',
            'pull-kubernetes-federation-e2e-gce': 'pull-kubernetes-federation-e2e-gce-*',
            'ci-kubernetes-pull-gce-federation-deploy': 'pull-kubernetes-federation-e2e-gce-*',
            'pull-kubernetes-federation-e2e-gce-canary': 'pull-kubernetes-federation-e2e-gce-*',
            'pull-kubernetes-e2e-gce': 'pull-kubernetes-e2e-gce-*',
            'pull-kubernetes-e2e-gce-canary': 'pull-kubernetes-e2e-gce-*',
            'ci-kubernetes-e2e-gce': 'ci-kubernetes-e2e-gce-*',
            'ci-kubernetes-e2e-gce-canary': 'ci-kubernetes-e2e-gce-*',
            'ci-kubernetes-e2e-gke-gpu': 'ci-kubernetes-e2e-gke-gpu-*',
            'pull-kubernetes-e2e-gke-gpu': 'ci-kubernetes-e2e-gke-gpu-*',
            'ci-kubernetes-node-kubelet-serial': 'ci-kubernetes-node-kubelet-*',
            'ci-kubernetes-node-kubelet-flaky': 'ci-kubernetes-node-kubelet-*',
            'ci-kubernetes-node-kubelet-conformance': 'ci-kubernetes-node-kubelet-*',
            'ci-kubernetes-node-kubelet-benchmark': 'ci-kubernetes-node-kubelet-*',
            'ci-kubernetes-node-kubelet': 'ci-kubernetes-node-kubelet-*',
        }
        for soak_prefix in [
                'ci-kubernetes-soak-gce-1.5',
                'ci-kubernetes-soak-gce-1-7',
                'ci-kubernetes-soak-gce-1.6',
                'ci-kubernetes-soak-gce-2',
                'ci-kubernetes-soak-gce',
                'ci-kubernetes-soak-gci-gce-1.5',
                'ci-kubernetes-soak-gce-gci',
                'ci-kubernetes-soak-gke-gci',
                'ci-kubernetes-soak-gce-federation',
                'ci-kubernetes-soak-gci-gce-stable1',
                'ci-kubernetes-soak-gci-gce-1.6',
                'ci-kubernetes-soak-gci-gce-1-7',
                'ci-kubernetes-soak-cos-docker-validation',
                'ci-kubernetes-soak-gke',
        ]:
            allowed_list['%s-deploy' % soak_prefix] = '%s-*' % soak_prefix
            allowed_list['%s-test' % soak_prefix] = '%s-*' % soak_prefix
        # pylint: enable=line-too-long
        projects = collections.defaultdict(set)
        boskos = []
        with open(config_sort.test_infra('boskos/resources.json')) as fp:
            for rtype in json.loads(fp.read()):
                if 'project' in rtype['type']:
                    for name in rtype['names']:
                        boskos.append(name)

        with open(config_sort.test_infra('jobs/config.json')) as fp:
            job_config = json.load(fp)
            for job in job_config:
                project = ''
                cfg = job_config.get(job.rsplit('.', 1)[0], {})
                if cfg.get('scenario') == 'kubernetes_e2e':
                    for arg in cfg.get('args', []):
                        if not arg.startswith('--gcp-project='):
                            continue
                        project = arg.split('=', 1)[1]
                if project:
                    if project in boskos:
                        self.fail('Project %s cannot be in boskos/resources.json!' % project)
                    projects[project].add(allowed_list.get(job, job))

        duplicates = [(p, j) for p, j in projects.items() if len(j) > 1]
        if duplicates:
            self.fail('Jobs duplicate projects:\n  %s' % (
                '\n  '.join('%s: %s' % t for t in duplicates)))

    def test_jobs_do_not_source_shell(self):
        for job, job_path in self.jobs:
            if job.startswith('pull-'):
                continue  # No clean way to determine version
            with open(job_path) as fp:
                script = fp.read()
            self.assertFalse(re.search(r'\Wsource ', script), job)
            self.assertNotIn('\n. ', script, job)

    def test_all_bash_jobs_have_errexit(self):
        options = {
            'errexit',
            'nounset',
            'pipefail',
        }
        for job, job_path in self.jobs:
            if not job.endswith('.sh'):
                continue
            with open(job_path) as fp:
                lines = list(fp)
            for option in options:
                expected = 'set -o %s\n' % option
                self.assertIn(
                    expected, lines,
                    '%s not found in %s' % (expected, job_path))

    def _check_env(self, job, setting):
        if not re.match(r'[0-9A-Z_]+=[^\n]*', setting):
            self.fail('[%r]: Env %r: need to follow FOO=BAR pattern' % (job, setting))
        if '#' in setting:
            self.fail('[%r]: Env %r: No inline comments' % (job, setting))
        if '"' in setting or '\'' in setting:
            self.fail('[%r]: Env %r: No quote in env' % (job, setting))
        if '$' in setting:
            self.fail('[%r]: Env %r: Please resolve variables in env' % (job, setting))
        if '{' in setting or '}' in setting:
            self.fail('[%r]: Env %r: { and } are not allowed in env' % (job, setting))
        # also test for https://github.com/kubernetes/test-infra/issues/2829
        # TODO(fejta): sort this list
        black = [
            ('CHARTS_TEST=', '--charts-tests'),
            ('CLUSTER_IP_RANGE=', '--test_args=--cluster-ip-range=FOO'),
            ('CLOUDSDK_BUCKET=', '--gcp-cloud-sdk=gs://foo'),
            ('CLUSTER_NAME=', '--cluster=FOO'),
            ('E2E_CLEAN_START=', '--test_args=--clean-start=true'),
            ('E2E_DOWN=', '--down=true|false'),
            ('E2E_MIN_STARTUP_PODS=', '--test_args=--minStartupPods=FOO'),
            ('E2E_NAME=', '--cluster=whatever'),
            ('E2E_PUBLISH_PATH=', '--publish=gs://FOO'),
            ('E2E_REPORT_DIR=', '--test_args=--report-dir=FOO'),
            ('E2E_REPORT_PREFIX=', '--test_args=--report-prefix=FOO'),
            ('E2E_TEST=', '--test=true|false'),
            ('E2E_UPGRADE_TEST=', '--upgrade_args=FOO'),
            ('E2E_UP=', '--up=true|false'),
            ('E2E_OPT=', 'Send kubetest the flags directly'),
            ('FAIL_ON_GCP_RESOURCE_LEAK=', '--check-leaked-resources=true|false'),
            ('FEDERATION_DOWN=', '--down=true|false'),
            ('FEDERATION_UP=', '--up=true|false'),
            ('GINKGO_PARALLEL=', '--ginkgo-parallel=# (1 for serial)'),
            ('GINKGO_PARALLEL_NODES=', '--ginkgo-parallel=# (1 for serial)'),
            ('GINKGO_TEST_ARGS=', '--test_args=FOO'),
            ('GINKGO_UPGRADE_TEST_ARGS=', '--upgrade_args=FOO'),
            ('JENKINS_FEDERATION_PREFIX=', '--stage=gs://FOO'),
            ('JENKINS_GCI_PATCH_K8S=', 'Unused, see --extract docs'),
            ('JENKINS_PUBLISHED_VERSION=', '--extract=V'),
            ('JENKINS_PUBLISHED_SKEW_VERSION=', '--extract=V'),
            ('JENKINS_USE_SKEW_KUBECTL=', 'SKEW_KUBECTL=y'),
            ('JENKINS_USE_SKEW_TESTS=', '--skew'),
            ('JENKINS_SOAK_MODE', '--soak'),
            ('JENKINS_SOAK_PREFIX', '--stage=gs://FOO'),
            ('JENKINS_USE_EXISTING_BINARIES=', '--extract=local'),
            ('JENKINS_USE_LOCAL_BINARIES=', '--extract=none'),
            ('JENKINS_USE_SERVER_VERSION=', '--extract=gke'),
            ('JENKINS_USE_GCI_VERSION=', '--extract=gci/FAMILY'),
            ('JENKINS_USE_GCI_HEAD_IMAGE_FAMILY=', '--extract=gci/FAMILY'),
            ('KUBE_GKE_NETWORK=', '--gcp-network=FOO'),
            ('KUBE_GCE_NETWORK=', '--gcp-network=FOO'),
            ('KUBE_GCE_ZONE=', '--gcp-zone=FOO'),
            ('KUBEKINS_TIMEOUT=', '--timeout=XXm'),
            ('KUBEMARK_TEST_ARGS=', '--test_args=FOO'),
            ('KUBEMARK_TESTS=', '--test_args=--ginkgo.focus=FOO'),
            ('KUBEMARK_MASTER_SIZE=', '--kubemark-master-size=FOO'),
            ('KUBEMARK_NUM_NODES=', '--kubemark-nodes=FOO'),
            ('KUBE_OS_DISTRIBUTION=', '--gcp-node-image=FOO and --gcp-master-image=FOO'),
            ('KUBE_NODE_OS_DISTRIBUTION=', '--gcp-node-image=FOO'),
            ('KUBE_MASTER_OS_DISTRIBUTION=', '--gcp-master-image=FOO'),
            ('KUBERNETES_PROVIDER=', '--provider=FOO'),
            ('PERF_TESTS=', '--perf'),
            ('PROJECT=', '--gcp-project=FOO'),
            ('SKEW_KUBECTL=', '--test_args=--kubectl-path=FOO'),
            ('USE_KUBEMARK=', '--kubemark'),
            ('ZONE=', '--gcp-zone=FOO'),
        ]
        for env, fix in black:
            if 'kops' in job and env in [
                    'JENKINS_PUBLISHED_VERSION=',
                    'JENKINS_USE_LOCAL_BINARIES=',
                    'GINKGO_TEST_ARGS=',
                    'KUBERNETES_PROVIDER=',
            ]:
                continue  # TOOD(fejta): migrate kops jobs
            if setting.startswith(env):
                self.fail('[%s]: Env %s: Convert %s to use %s in jobs/config.json' % (
                    job, setting, env, fix))

    def test_envs_no_export(self):
        for job, job_path in self.jobs:
            if not job.endswith('.env'):
                continue
            with open(job_path) as fp:
                lines = list(fp)
            for line in lines:
                line = line.strip()
                self.assertFalse(line.endswith('\\'))
                if not line:
                    continue
                if line.startswith('#'):
                    continue
                self._check_env(job, line)

    def test_envs_non_empty(self):
        bad = []
        for job, job_path in self.jobs:
            if not job.endswith('.env'):
                continue
            with open(job_path) as fp:
                lines = list(fp)
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#'):
                    break
            else:
                bad.append(job)
        if bad:
            self.fail('%s is empty, please remove the file(s)' % bad)

    def test_no_bad_vars_in_jobs(self):
        """Searches for jobs that contain ${{VAR}}"""
        for job, job_path in self.jobs:
            with open(job_path) as fp:
                script = fp.read()
            bad_vars = re.findall(r'(\${{.+}})', script)
            if bad_vars:
                self.fail('Job %s contains bad bash variables: %s' % (job, ' '.join(bad_vars)))

if __name__ == '__main__':
    unittest.main()
