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

import datetime
import json
import logging
import os
import time

import filters
import gcs_async
import github.models as ghm
import pull_request
import view_base


@view_base.memcache_memoize('pr-details://', expires=60 * 3)
def pr_builds(path):
    """Return {job: [(build, {started.json}, {finished.json})]} for each job under gcs path."""
    jobs_dirs_fut = gcs_async.listdirs(path)

    def base(path):
        return os.path.basename(os.path.dirname(path))

    jobs_futures = [(job, gcs_async.listdirs(job)) for job in jobs_dirs_fut.get_result()]
    futures = []

    for job, builds_fut in jobs_futures:
        for build in builds_fut.get_result():
            futures.append([
                base(job),
                base(build),
                gcs_async.read('/%sstarted.json' % build),
                gcs_async.read('/%sfinished.json' % build)])

    futures.sort(key=lambda (job, build, s, f): (job, view_base.pad_numbers(build)), reverse=True)

    jobs = {}
    for job, build, started_fut, finished_fut in futures:
        started = started_fut.get_result()
        finished = finished_fut.get_result()
        if started is not None:
            started = json.loads(started)
        if finished is not None:
            finished = json.loads(finished)
        jobs.setdefault(job, []).append((build, started, finished))

    return jobs


def pr_path(org, repo, pr, default_org, default_repo, pull_prefix):
    """Builds the correct gs://prefix/maybe_kubernetes/maybe_repo_org/pr."""
    if org == default_org and repo == default_repo:
        return '%s/%s' % (pull_prefix, pr)
    if org == default_org:
        return '%s/%s/%s' % (pull_prefix, repo, pr)
    return '%s/%s_%s/%s' % (pull_prefix, org, repo, pr)


def org_repo(path, default_org, default_repo):
    """Converts /maybe_org/maybe_repo into (org, repo)."""
    parts = path.split('/')[1:]
    if len(parts) == 2:
        org, repo = parts
    elif len(parts) == 1:
        org = default_org
        repo = parts[0]
    else:
        org = default_org
        repo = default_repo
    return org, repo


class PRHandler(view_base.BaseHandler):
    """Show a list of test runs for a PR."""
    def get(self, path, pr):
        # pylint: disable=too-many-locals
        org, repo = org_repo(path=path,
            default_org=self.app.config['default_org'],
            default_repo=self.app.config['default_repo'],
        )
        path = pr_path(org=org, repo=repo, pr=pr,
            pull_prefix=self.app.config['external_services'][org]['gcs_pull_prefix'],
            default_org=self.app.config['default_org'],
            default_repo=self.app.config['default_repo'],
        )
        builds = pr_builds(path)
        # TODO(fejta): assume all builds are monotonically increasing.
        for bs in builds.itervalues():
            if any(len(b) > 8 for b, _, _ in bs):
                bs.sort(key=lambda (b, s, f): -(s or {}).get('timestamp', 0))
        if pr == 'batch':  # truncate batch results to last day
            cutoff = time.time() - 60 * 60 * 24
            builds = {}
            for job, job_builds in builds.iteritems():
                builds[job] = [
                    (b, s, f) for b, s, f in job_builds
                    if not s or s.get('timestamp') > cutoff
                ]

        max_builds, headings, rows = pull_request.builds_to_table(builds)
        digest = ghm.GHIssueDigest.get('%s/%s' % (org, repo), pr)
        self.render(
            'pr.html',
            dict(
                pr=pr,
                digest=digest,
                max_builds=max_builds,
                header=headings,
                org=org,
                repo=repo,
                rows=rows,
                path=path,
            )
        )


def get_acks(login, prs):
    acks = {}
    result = ghm.GHUserState.make_key(login).get()
    if result:
        acks = result.acks
        if prs:
            # clear acks for PRs that user is no longer involved in.
            stale = set(acks) - set(pr.key.id() for pr in prs)
            if stale:
                for key in stale:
                    result.acks.pop(key)
                result.put()
    return acks


class PRDashboard(view_base.BaseHandler):
    def get(self, user=None):
        # pylint: disable=singleton-comparison
        login = self.session.get('user')
        if not user:
            user = login
            if not user:
                self.redirect('/github_auth/pr')
                return
            logging.debug('user=%s', user)
        elif user == 'all':
            user = None
        qs = [ghm.GHIssueDigest.is_pr == True]
        if not self.request.get('all', False):
            qs.append(ghm.GHIssueDigest.is_open == True)
        if user:
            qs.append(ghm.GHIssueDigest.involved == user)
        prs = list(ghm.GHIssueDigest.query(*qs))
        prs.sort(key=lambda x: x.updated_at, reverse=True)

        acks = None
        if login and user == login:  # user getting their own page
            acks = get_acks(login, prs)

        fmt = self.request.get('format', 'html')
        if fmt == 'json':
            self.response.headers['Content-Type'] = 'application/json'
            def serial(obj):
                if isinstance(obj, datetime.datetime):
                    return obj.isoformat()
                elif isinstance(obj, ghm.GHIssueDigest):
                    # pylint: disable=protected-access
                    keys = ['repo', 'number'] + list(obj._values)
                    return {k: getattr(obj, k) for k in keys}
                raise TypeError
            self.response.write(json.dumps(prs, sort_keys=True, default=serial))
        elif fmt == 'html':
            if user:
                def acked(p):
                    if 'lgtm' in p.payload.get('labels', {}):
                        return True  # LGTM is an implicit Ack
                    if acks is None:
                        return False
                    return filters.do_get_latest(p.payload, user) <= acks.get(p.key.id(), 0)
                cats = [
                    ('Needs Attention', lambda p: user in p.payload['attn'] and not acked(p), ''),
                    ('Approvable', lambda p: user in p.payload.get('approvers', []),
                     'is:open is:pr ("additional approvers: {0}" ' +
                     'OR "additional approver: {0}")'.format(user)),
                    ('Incoming', lambda p: user != p.payload['author'] and
                                           user in p.payload['assignees'],
                     'is:open is:pr user:kubernetes assignee:%s' % user),
                    ('Outgoing', lambda p: user == p.payload['author'],
                     'is:open is:pr user:kubernetes author:%s' % user),
                ]
            else:
                cats = [('Open Kubernetes PRs', lambda x: True,
                    'is:open is:pr user:kubernetes')]

            self.render('pr_dashboard.html', dict(
                prs=prs, cats=cats, user=user, login=login, acks=acks))
        else:
            self.abort(406)

    def post(self):
        login = self.session.get('user')
        if not login:
            self.abort(403)
        state = ghm.GHUserState.make_key(login).get()
        if state is None:
            state = ghm.GHUserState.make(login)
        body = json.loads(self.request.body)
        if body['command'] == 'ack':
            delta = {'%s %s' % (body['repo'], body['number']): body['latest']}
            state.acks.update(delta)
            state.put()
        elif body['command'] == 'ack-clear':
            state.acks = {}
            state.put()
        else:
            self.abort(400)


class PRBuildLogHandler(view_base.BaseHandler):
    def get(self, path):
        org, _ = org_repo(path=path,
            default_org=self.app.config['default_org'],
            default_repo=self.app.config['default_repo'],
        )
        self.redirect('https://storage.googleapis.com/%s/%s' % (
            self.app.config['external_services'][org]['gcs_pull_prefix'], path
        ))
