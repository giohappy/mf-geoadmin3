#!/bin/bash

#bail out on any error
set -o errexit

# set some variables and default

GIT_CLONE_OPTS=""
SNAPSHOTDIR=${@:$OPTIND:1}
GITBRANCH=${@:$OPTIND+1:1}

GITBRANCH=${GITBRANCH:-master}

if [ ! -d "${SNAPSHOTDIR}" ]; then
    mkdir -p "${SNAPSHOTDIR}"
fi

echo "Cloning branch=${GITBRANCH}, into directory=${SNAPSHOTDIR}"

cd ${SNAPSHOTDIR}

git clone ${GIT_CLONE_OPTS} -b ${GITBRANCH}  https://github.com/geoadmin/mf-geoadmin3.git   

cd mf-geoadmin3

echo "Reseting repository to HEAD for branch=${GITBRANCH}"
git reset --hard origin/$GITBRANCH

echo "Building the project"
RC_FILE=rc_${DEPLOY_TARGET}
source $RC_FILE
make cleanall all
