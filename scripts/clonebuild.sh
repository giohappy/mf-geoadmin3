#!/bin/bash

#bail out on any error
set -o errexit

# set some variables and default

GIT_CLONE_OPTS=""
SNAPSHOTDIR=${@:$OPTIND:1}
DEPLOY_GIT_BRANCH=${@:$OPTIND+1:1}

DEPLOY_GIT_BRANCH=${DEPLOY_GIT_BRANCH:-master}

if [ ! -d "${SNAPSHOTDIR}" ]; then
    mkdir -p "${SNAPSHOTDIR}"
fi

echo "Cloning branch=${DEPLOY_GIT_BRANCH}, into directory=${SNAPSHOTDIR}"

cd ${SNAPSHOTDIR}

git clone ${GIT_CLONE_OPTS} -b ${DEPLOY_GIT_BRANCH}  https://github.com/geoadmin/mf-geoadmin3.git

cd mf-geoadmin3

echo "Reseting repository to HEAD for branch=${DEPLOY_GIT_BRANCH}"
git reset --hard origin/$DEPLOY_GIT_BRANCH

echo "Building the project"
make cleanall all
