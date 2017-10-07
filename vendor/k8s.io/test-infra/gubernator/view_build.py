# Copyright 2016 The Kubernetes Authors.
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

import logging
import json
import os
import re

import defusedxml.ElementTree as ET

from google.appengine.api import urlfetch

import gcs_async
from github import models
import log_parser
import testgrid
import view_base


class JUnitParser(object):
    def __init__(self):
        self.skipped = []
        self.passed = []
        self.failed = []

    def handle_suite(self, tree, filename):
        for subelement in tree:
            if subelement.tag == 'testsuite':
                self.handle_suite(subelement, filename)
            elif subelement.tag == 'testcase':
                if 'name' in tree.attrib:
                    name_prefix = tree.attrib['name'] + ' '
                else:
                    name_prefix = ''
                self.handle_test(subelement, filename, name_prefix)

    def handle_test(self, child, filename, name_prefix=''):
        name = name_prefix + child.attrib['name']
        if child.find('skipped') is not None:
            self.skipped.append(name)
        elif child.find('failure') is not None:
            time = float(child.attrib['time'])
            out = []
            for param in child.findall('system-out'):
                out.append(param.text)
            for param in child.findall('system-err'):
                out.append(param.text)
            for param in child.findall('failure'):
                self.failed.append((name, time, param.text, filename, '\n'.join(out)))
        else:
            self.passed.append(name)

    def parse_xml(self, xml, filename):
        if not xml:
            return  # can't extract results from nothing!
        try:
            tree = ET.fromstring(xml)
        except ET.ParseError, e:
            logging.exception('parse_junit failed for %s', filename)
            try:
                tree = ET.fromstring(re.sub(r'[\x00\x80-\xFF]+', '?', xml))
            except ET.ParseError, e:
                self.failed.append(
                    ('Gubernator Internal Fatal XML Parse Error', 0.0, str(e), filename, ''))
                return
        if tree.tag == 'testsuite':
            self.handle_suite(tree, filename)
        elif tree.tag == 'testsuites':
            for testsuite in tree:
                self.handle_suite(testsuite, filename)
        else:
            logging.error('unable to find failures, unexpected tag %s', tree.tag)

    def get_results(self):
        self.failed.sort()
        self.skipped.sort()
        self.passed.sort()
        return {
            'failed': self.failed,
            'skipped': self.skipped,
            'passed': self.passed,
        }


@view_base.memcache_memoize('build-log-parsed://', expires=60*60*4)
def get_build_log(build_dir):
    build_log = gcs_async.read(build_dir + '/build-log.txt').get_result()
    if build_log:
        return log_parser.digest(build_log)


def get_running_build_log(job, build, prow_url):
    try:
        url = "https://%s/log?job=%s&id=%s" % (prow_url, job, build)
        result = urlfetch.fetch(url)
        if result.status_code == 200:
            return log_parser.digest(result.content), url
    except urlfetch.Error:
        logging.exception('Caught exception fetching url')
    return None, None


@view_base.memcache_memoize('build-details://', expires=60)
def build_details(build_dir):
    """
    Collect information from a build directory.

    Args:
        build_dir: GCS path containing a build's results.
    Returns:
        started: value from started.json {'version': ..., 'timestamp': ...}
        finished: value from finished.json {'timestamp': ..., 'result': ...}
        results: {total: int,
                  failed: [(name, duration, text)...],
                  skipped: [name...],
                  passed: [name...]}
    """
    started_fut = gcs_async.read(build_dir + '/started.json')
    finished = gcs_async.read(build_dir + '/finished.json').get_result()
    started = started_fut.get_result()
    if finished and not started:
        started = 'null'
    if started and not finished:
        finished = 'null'
    elif not (started and finished):
        return
    started = json.loads(started)
    finished = json.loads(finished)

    junit_paths = [f.filename for f in view_base.gcs_ls('%s/artifacts' % build_dir)
                   if re.match(r'junit_.*\.xml', os.path.basename(f.filename))]

    junit_futures = {f: gcs_async.read(f) for f in junit_paths}

    parser = JUnitParser()
    for path, future in junit_futures.iteritems():
        parser.parse_xml(future.get_result(), path)
    return started, finished, parser.get_results()


def parse_pr_path(gcs_path, default_org, default_repo):
    """
    Parse GCS bucket directory into metadata. We
    allow for two short-form names and one long one:

     gs://<pull_prefix>/<pull_number>
      -- this fills in the default repo and org

     gs://<pull_prefix>/repo/<pull_number>
      -- this fills in the default org

     gs://<pull_prefix>/org_repo/<pull_number>

    :param gcs_path: GCS bucket directory for a build
    :return: tuple of:
     - PR number
     - Gubernator PR link
     - PR repo
    """
    pull_number = os.path.basename(gcs_path)
    parsed_repo = os.path.basename(os.path.dirname(gcs_path))
    if parsed_repo == 'pull':
        pr_path = ''
        repo = '%s/%s' % (default_org, default_repo)
    elif '_' not in parsed_repo:
        pr_path = parsed_repo + '/'
        repo = '%s/%s' % (default_org, parsed_repo)
    else:
        pr_path = parsed_repo.replace('_', '/') + '/'
        repo = parsed_repo.replace('_', '/')
    return pull_number, pr_path, repo


class BuildHandler(view_base.BaseHandler):
    """Show information about a Build and its failing tests."""
    def get(self, prefix, job, build):
        # pylint: disable=too-many-locals
        if prefix.endswith('/directory'):
            # redirect directory requests
            link = gcs_async.read('/%s/%s/%s.txt' % (prefix, job, build)).get_result()
            if link and link.startswith('gs://'):
                self.redirect('/build/' + link.replace('gs://', ''))
                return

        job_dir = '/%s/%s/' % (prefix, job)
        testgrid_query = testgrid.path_to_query(job_dir)
        build_dir = job_dir + build
        details = build_details(build_dir)
        if not details:
            logging.warning('unable to load %s', build_dir)
            self.render(
                'build_404.html',
                dict(build_dir=build_dir, job_dir=job_dir, job=job, build=build))
            self.response.set_status(404)
            return
        started, finished, results = details

        want_build_log = False
        build_log = ''
        build_log_src = None
        if 'log' in self.request.params or (not finished) or \
            (finished and finished.get('result') != 'SUCCESS' and len(results['failed']) <= 1):
            want_build_log = True
            build_log = get_build_log(build_dir)

        pr, pr_path, pr_digest, repo = None, None, None, None
        external_config = get_pr_config(prefix, self.app.config)
        if external_config is not None:
            pr, pr_path, pr_digest, repo = get_pr_info(prefix, self.app.config)
            if want_build_log and not build_log:
                build_log, build_log_src = get_running_build_log(job, build,
                                                                 external_config["prow_url"])

        # 'version' might be in either started or finished.
        # prefer finished.
        if finished and 'version' in finished:
            version = finished['version']
        else:
            version = started and started.get('version')
        commit = version and version.split('+')[-1]

        issues = list(models.GHIssueDigest.find_xrefs(build_dir))

        refs = []
        if started and 'pull' in started:
            for ref in started['pull'].split(','):
                x = ref.split(':', 1)
                if len(x) == 2:
                    refs.append((x[0], x[1]))
                else:
                    refs.append((x[1], ''))

        self.render('build.html', dict(
            job_dir=job_dir, build_dir=build_dir, job=job, build=build,
            commit=commit, started=started, finished=finished,
            res=results, refs=refs,
            build_log=build_log, build_log_src=build_log_src,
            issues=issues, repo=repo,
            pr_path=pr_path, pr=pr, pr_digest=pr_digest,
            testgrid_query=testgrid_query))


def get_pr_config(prefix, config):
    for item in config["external_services"].values():
        if prefix.startswith(item["gcs_pull_prefix"]):
            return item

def get_pr_info(prefix, config):
    if config is not None:
        pr, pr_path, repo = parse_pr_path(
            gcs_path=prefix,
            default_org=config['default_org'],
            default_repo=config['default_repo'],
        )
        pr_digest = models.GHIssueDigest.get(repo, pr)
        return pr, pr_path, pr_digest, repo

def get_running_pr_log(job, build, config):
    if config is not None:
        return get_running_build_log(job, build, config["prow_url"])

def get_build_numbers(job_dir, before, indirect):
    try:
        if '/pull/' in job_dir and not indirect:
            raise ValueError('bad code path for PR build list')
        # If we have latest-build.txt, we can skip an expensive GCS ls call!
        if before:
            latest_build = int(before) - 1
        else:
            latest_build = int(gcs_async.read(job_dir + 'latest-build.txt').get_result())
            # latest-build.txt has the most recent finished build. There might
            # be newer builds that have started but not finished. Probe for them.
            suffix = '/started.json' if not indirect else '.txt'
            while gcs_async.read('%s%s%s' % (job_dir, latest_build + 1, suffix)).get_result():
                latest_build += 1
        return range(latest_build, max(0, latest_build - 40), -1)
    except (ValueError, TypeError):
        fstats = view_base.gcs_ls(job_dir)
        fstats.sort(key=lambda f: view_base.pad_numbers(f.filename),
                    reverse=True)
        if indirect:
            # find numbered builds
            builds = [re.search(r'/(\d*)\.txt$', f.filename)
                      for f in fstats if not f.is_dir]
            builds = [m.group(1) for m in builds if m]
        else:
            builds = [os.path.basename(os.path.dirname(f.filename))
                      for f in fstats if f.is_dir]
        if before and before in builds:
            builds = builds[builds.index(before) + 1:]
        return builds[:40]


@view_base.memcache_memoize('build-list://', expires=60)
def build_list(job_dir, before):
    '''
    Given a job dir, give a (partial) list of recent build
    finished.jsons.

    Args:
        job_dir: the GCS path holding the jobs
    Returns:
        a list of [(build, finished)]. build is a string like "123",
        finished is either None or a dict of the finished.json.
    '''

    # /directory/ folders have a series of .txt files pointing at the correct location,
    # as a sort of fake symlink.
    indirect = '/directory/' in job_dir

    builds = get_build_numbers(job_dir, before, indirect)

    if indirect:
        # follow the indirect links
        build_symlinks = [
            (build,
             gcs_async.read('%s%s.txt' % (job_dir, build)))
            for build in builds
        ]
        build_futures = []
        for build, sym_fut in build_symlinks:
            redir = sym_fut.get_result()
            if redir and redir.startswith('gs://'):
                redir = redir[4:].strip()
                build_futures.append(
                    (build, redir,
                     gcs_async.read('%s/started.json' % redir),
                     gcs_async.read('%s/finished.json' % redir)))
    else:
        build_futures = [
            (build, '%s%s' % (job_dir, build),
             gcs_async.read('%s%s/started.json' % (job_dir, build)),
             gcs_async.read('%s%s/finished.json' % (job_dir, build)))
            for build in builds
        ]

    def resolve(future):
        res = future.get_result()
        if res:
            return json.loads(res)

    return [(str(build), loc, resolve(started), resolve(finished))
            for build, loc, started, finished in build_futures]

class BuildListHandler(view_base.BaseHandler):
    """Show a list of Builds for a Job."""
    def get(self, prefix, job):
        job_dir = '/%s/%s/' % (prefix, job)
        testgrid_query = testgrid.path_to_query(job_dir)
        before = self.request.get('before')
        builds = build_list(job_dir, before)
        dir_link = re.sub(r'/pull/.*', '/directory/%s' % job, prefix)
        self.render('build_list.html',
                    dict(job=job, job_dir=job_dir, dir_link=dir_link,
                         testgrid_query=testgrid_query,
                         builds=builds, before=before))


class JobListHandler(view_base.BaseHandler):
    """Show a list of Jobs in a directory."""
    def get(self, prefix):
        jobs_dir = '/%s' % prefix
        fstats = view_base.gcs_ls(jobs_dir)
        fstats.sort()
        self.render('job_list.html', dict(jobs_dir=jobs_dir, fstats=fstats))
