#!/bin/sh
# vim:et:ai:ts=4:sw=4:filetype=sh:

set -e
set -x

cur_dir=$(cd $(dirname $0); pwd)
cd $cur_dir/../

[ -n "$APT_REPO" ] || 
    APT_REPO=/var/ftp/pub/yum/dell-repo/testing/debian/

. version.mk
RELEASE_VERSION=${RELEASE_MAJOR}.${RELEASE_MINOR}.${RELEASE_SUBLEVEL}${RELEASE_EXTRALEVEL}
RELEASE_STRING=${RELEASE_NAME}-${RELEASE_VERSION}

make distclean
make deb

# need to port the following to pbuilder
mkdir -p ${APT_REPO}/etch-i386/${RELEASE_NAME}/${RELEASE_VERSION}-${DEB_RELEASE}/

DEST=${APT_REPO}/etch-i386/${RELEASE_NAME}/${RELEASE_VERSION}-${DEB_RELEASE}/
for file in build/*
do
    [ -e $DEST/$(basename $file) ] || cp $file $DEST/
done

