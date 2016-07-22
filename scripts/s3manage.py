# -*- coding: utf-8 -*-

import re
import botocore
import boto3
import sys
import os
import json
import subprocess
import urllib2

import StringIO
import gzip
from datetime import datetime
from textwrap import dedent
import mimetypes


def usage():
    print(dedent('''\
        Manage map.geo.admin.ch versions in AWS S3 bucket. Please make sure all your env variables are set.
        (namely S3_MF_GEOADMIN3_INFRA and DEPLOY_TARGET)

        Usage:

            .build-artefacts/python-venv/bin/python scripts/s3manage.py <upload|list|info|delete> <options>

        Commands:

            upload: Upload content of /prd (and /src) directory to a bucket.
                    You may specify a directory (it defaults to current).

                    Example: python scripts/s3manage.py <deploy_target> <snapshotdir>

            list:   List available <version> in a bucket.

                    Example: python scripts/s3manage.py list

            info:   Print the info.json file.

                    Example: python scripts/s3manage.py info <deploy_target>/<branch_name>/<sha>/<version>

            delete: Delete an existing project.

                    Example: python scripts/s3manage.py delete <deploy_target>/<branch_name>/<sha>/<version>
    '''))


mimetypes.init()
mimetypes.add_type('application/x-font-ttf', '.ttf')
mimetypes.add_type('application/x-font-opentype', '.otf')
mimetypes.add_type('application/vnd.ms-fontobject', '.eot')

NO_COMPRESS = [
    'image/png',
    'image/jpeg',
    'image/ico',
    'application/x-font-ttf',
    'application/x-font-opentype',
    'application/vnd.ms-fontobject',
    'application/vnd.ms-fontobject']


def local_git_last_commit(basedir):
    try:
        output = subprocess.check_output(('git rev-parse HEAD',), cwd=basedir, shell=True)
        return output.strip()
    except subprocess.CalledProcessError:
        print('Not a git directory: %s' % basedir)
    try:
        with open(os.path.join(basedir, '.build-artefacts', 'last-commit-ref'), 'r') as f:
            data = f.read()
        return data
    except IOError:
        print('Error while reading \'last-commit-ref\' from %s' % basedir)
    return None


def local_git_branch(basedir):
    output = subprocess.check_output(('git rev-parse --abbrev-ref HEAD',), cwd=basedir, shell=True)
    return output.strip()


def local_last_version(basedir):
    try:
        with open(os.path.join(basedir, '.build-artefacts', 'last-version'), 'r') as f:
            data = f.read()
        return data
    except IOError as e:
        print('Cannot find version: %s' % e)
    return None


def _gzip_data(data):
    out = None
    infile = StringIO.StringIO()
    try:
        gzip_file = gzip.GzipFile(fileobj=infile, mode='w', compresslevel=5)
        gzip_file.write(data)
        gzip_file.close()
        infile.seek(0)
        out = infile.getvalue()
    except:
        out = None
    finally:
        infile.close()
    return out


def _unzip_data(compressed):
    inbuffer = StringIO.StringIO(compressed)
    f = gzip.GzipFile(mode='rb', fileobj=inbuffer)
    try:
        data = f.read()
    finally:
        f.close()

    return data


def save_to_s3(src, dest, bucket_name, cached=True, mimetype=None, break_on_error=False):
    try:
        with open(src, 'r') as f:
            data = f.read()
    except EnvironmentError as e:
        print('Failed to upload %s' % src)
        print(str(e))
        if break_on_error:
            print("Exiting...")
            sys.exit(1)
        else:
            return False
    _save_to_s3(data, dest, mimetype, bucket_name, cached=cached)


def _save_to_s3(in_data, dest, mimetype, bucket_name, compress=True, cached=True):
    data = in_data
    compressed = False
    content_encoding = None
    cache_control = 'max-age=31536000, public'
    extra_args = {}

    if compress and mimetype not in NO_COMPRESS:
        data = _gzip_data(in_data)
        content_encoding = 'gzip'
        compressed = True

    if cached is False:
        cache_control = 'no-cache, no-store, max-age=0, must-revalidate'

    extra_args['ACL'] = 'public-read'
    extra_args['ContentType'] = mimetype
    extra_args['CacheControl'] = cache_control

    try:
        print('Uploading to %s - %s, gzip: %s, cache headers: %s' % (dest, mimetype, compressed, cached))
        if compressed:
            extra_args['ContentEncoding'] = content_encoding

        if cached is False:
            extra_args['Expires'] = datetime(1990, 1, 1)
            extra_args['Metadata'] = {'Pragma': 'no-cache', 'Vary': '*'}

        s3.Object(bucket_name, dest).put(Body=data, **extra_args)
    except Exception as e:
        print('Error while uploading %s: %s' % (dest, e))


def get_index_version(c):
    version = None
    p = re.compile(ur'version: \'(\d+)\'')
    match = re.findall(p, c)
    if len(match) > 0:
        version = int(match[0])
    return version


def create_s3_dir_path(target, base_dir):
    git_short_sha = local_git_last_commit(base_dir)[:7]
    git_branch = local_git_branch(base_dir)
    version = local_last_version(base_dir).strip()
    return (os.path.join(target, git_branch, git_short_sha, version), version)


def is_cached(file_name):
    # 1 exception
    if file_name == 'services':
        return True
    _, extension = os.path.splitext(file_name)
    return bool(extension not in ['.html', '.txt', '.appcache', ''])


def get_file_mimetype(local_file):
    if local_file.endswith('.json') or local_file.endswith('services'):
        return 'application/json'
    elif local_file.endswith('.appcache'):
        return 'text/cache-manifest'
    elif local_file.endswith('.txt'):
        return 'text/plain'
    else:
        mimetype, _ = mimetypes.guess_type(local_file)
        if mimetype:
            return mimetype
        return 'text/plain'


def upload(bucket_name, target, base_dir):
    s3_dir_path, version = create_s3_dir_path(target, base_dir)
    print('Destionation folder is:')
    print('%s' % s3_dir_path)

    upload_directories = ['prd']
    if target != 'prod':
        upload_directories.append('src')
    exclude_filename_patterns = ['.less', '.gitignore', '.mako.']

    for directory in upload_directories:
        for file_path_list in os.walk(os.path.join(base_dir, directory)):
            file_names = file_path_list[2]
            if len(file_names) > 0:
                for file_name in file_names:
                    file_base_path = file_path_list[0]
                    if len([p for p in exclude_filename_patterns if p in file_name]) == 0:
                        is_chsdi_cache = bool(file_base_path.endswith('cache'))
                        local_file = os.path.join(file_base_path, file_name)
                        file_base_path = file_base_path.replace('cache', '')
                        if directory == 'prd':
                            if file_name in ('index.html', 'mobile.html', 'embed.html'):
                                file_base_path = file_base_path.replace('prd', '')
                            else:
                                file_base_path = file_base_path.replace('prd', version)
                        relative_file_path = file_base_path.replace(base_dir + '/', '')
                        remote_file = os.path.join(s3_dir_path, relative_file_path, file_name)
                        # Don't cache some files
                        cached = is_cached(file_name)
                        mimetype = get_file_mimetype(local_file)
                        save_to_s3(local_file, remote_file, bucket_name, cached=cached, mimetype=mimetype)
                        # Also upload chsdi metadata file to src folder if available
                        if is_chsdi_cache:
                            relative_file_path = relative_file_path.replace(version + '/', '')
                            remote_file = os.path.join(s3_dir_path, 'src/', relative_file_path, file_name)
                            save_to_s3(local_file, remote_file, bucket_name, cached=cached, mimetype=mimetype)

    # TODO replace me!
    url_to_check = 'https://mf-geoadmin3.infra.bgdi.ch/'
    print('Upload completed at %s%s/index.html' % (url_to_check, s3_dir_path))


def version_exists(version):
    files = bucket.objects.filter(Prefix=str(version)).all()
    return len(list(files)) > 0


def get_version_info(version):
    print('App version is: %s' % version)
    version_target = version.split('/')[3]
    obj = s3.Object(bucket.name, '%s/%s/info.json' % (version, version_target))
    try:
        content = obj.get()["Body"].read()
        raw = _unzip_data(content)
        data = json.loads(raw)
    except botocore.exceptions.ClientError:
        return None
    except botocore.exceptions.BotoCoreError:
        return None
    return data


def get_head_sha(branch):
    resp = urllib2.urlopen(
        'https://api.github.com/repos/geoadmin/mf-geoadmin3/commits?sha={}'.format(branch.replace('/', '')))
    data = json.load(resp)
    return data[0]['sha']


def list_version(bucket):
    envs = bucket.meta.client.list_objects(Bucket=bucket.name,
                                           Delimiter='/')
    for o in envs.get('CommonPrefixes'):
        env = o.get('Prefix')
        branches = bucket.meta.client.list_objects(Bucket=bucket.name,
                                                   Prefix=env,
                                                   Delimiter='/')
        for b in branches.get('CommonPrefixes'):
            head_sha = None
            branch = b.get('Prefix')
            if re.search(r'^\D', branch):
                shas = bucket.meta.client.list_objects(Bucket=bucket.name,
                                                       Prefix=branch,
                                                       Delimiter='/')
                for s in shas.get('CommonPrefixes'):
                    sha = s.get('Prefix')
                    nice_sha = sha.replace(branch, '').replace('/', '')

                    if head_sha is None:
                        branch_name = branch.replace(env, '')
                        head_sha = get_head_sha(branch_name)
                        is_head = 'HEAD' if nice_sha in head_sha else 'NOT HEAD'
                    print(branch)
                    print('  {} - {} ({})'.format(nice_sha, is_head, head_sha))
                    builds = bucket.meta.client.list_objects(Bucket=bucket.name,
                                                             Prefix=sha,
                                                             Delimiter='/')
                    for v in builds.get('CommonPrefixes'):
                        build = v.get('Prefix')
                        print('    ' + build.replace(sha, ''))


def version_info(version):
    info = get_version_info(version)
    if info is None:
        print('No info for version %s' % version)
        sys.exit(1)
    for k in info.keys():
        print('%s: %s' % (k, info[k]))


def delete_version(version, bucket_name):
    if version_exists(version) is False:
        print("Version '{}' does not exists in AWS S3. Aborting".format(version))
        sys.exit(1)

    files = bucket.objects.filter(Prefix=str(version)).all()

    indexes = [{'Key': k.key} for k in files]
    for n in ('index', 'embed', 'mobile'):
        src_key_name = '{}.{}.html'.format(n, version)
        indexes.append({'Key': src_key_name})

    resp = s3client.delete_objects(Bucket=bucket_name, Delete={'Objects': indexes})
    for v in resp['Deleted']:
        print v


def init_connection(bucket_name, profile_name):
    try:
        session = boto3.session.Session(profile_name=profile_name)
    except botocore.exceptions.ProfileNotFound as e:
        print('You need to set PROFILE_NAME to a valid profile name in $HOME/.aws/credentials')
        print(e)
        sys.exit(1)
    except botocore.exceptions.BotoCoreError as e:
        print('Cannot establish connection. Check you credentials %s.' % profile_name)
        print(e)
        sys.exit(1)

    s3client = session.client('s3', config=boto3.session.Config(signature_version='s3v4'))
    s3 = session.resource('s3', config=boto3.session.Config(signature_version='s3v4'))

    bucket = s3.Bucket(bucket_name)
    return (s3, s3client, bucket)


def exit_usage(cmd_type):
    print('Missing one arg for %s command' % cmd_type)
    usage()
    sys.exit(1)


def parse_arguments():
    if len(sys.argv) < 2:
        exit_usage('UNKNOWN')

    cmd_type = str(sys.argv[1])
    supported_cmds = ('upload', 'list', 'info', 'delete')
    if cmd_type not in supported_cmds:
        print('Command %s not supported' % cmd_type)
        usage()
        sys.exit(1)

    if cmd_type == 'upload' and len(sys.argv) < 3:
        exit_usage(cmd_type)
    elif cmd_type == 'list' and len(sys.argv) != 2:
        exit_usage(cmd_type)
    elif cmd_type == 'info' and len(sys.argv) < 3:
        exit_usage(cmd_type)
    elif cmd_type == 'delete' and len(sys.argv) < 3:
        exit_usage(cmd_type)

    target = None
    base_dir = os.getcwd()
    if cmd_type == 'upload' and len(sys.argv) == 4:
        base_dir = os.path.abspath(sys.argv[3])
        if not os.path.isdir(base_dir):
            print('No code found in directory %s' % base_dir)
            sys.exit(1)
        target = os.environ.get('DEPLOY_TARGET', None)
        if target not in ['dev', 'int', 'prod']:
            print('Unknown DEPLOY_TARGET=%s' % target)
            usage()
            sys.exit(1)

    if cmd_type == 'info' and len(sys.argv) == 3:
        target = sys.argv[2]
        if target.endswith('/'):
            target = target[:len(target) - 1]
        if target.count('/') != 3:
            print('Bad version definition')
            usage()
            sys.exit(1)

    # TODO handle git branch in env
    bucket_name_env = 'S3_MF_GEOADMIN3_INFRA'
    bucket_name = os.environ.get(bucket_name_env)
    if bucket_name is None:
        print('%s env variable is not defined' % bucket_name_env)
        usage()
        sys.exit(1)
    user = os.environ.get('USER')
    profile_name = '{}_aws_admin'.format(user)

    return (cmd_type, base_dir, bucket_name, target, profile_name)


def main():
    global s3, s3client, bucket
    cmd_type, base_dir, bucket_name, target, profile_name = parse_arguments()
    s3, s3client, bucket = init_connection(bucket_name, profile_name)

    if cmd_type == 'upload':
        upload(bucket_name, target, base_dir)
    elif cmd_type == 'list':
        if len(sys.argv) < 2:
            usage()
            sys.exit(1)
        list_version(bucket)
    elif cmd_type == 'info':
        version_info(target)
    elif str(sys.argv[1]) == 'delete' and len(sys.argv) == 3:
        version = int(sys.argv[2])
        print("Trying to delete version '{}'".format(version))
        delete_version(version, bucket_name)
    else:
        usage()

if __name__ == '__main__':
    main()
