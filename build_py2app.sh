#!/bin/sh
#
# Build py2app on MY OS X box, needs:
#
# o hellanzb installed via darwinports
# o py2app installed via darwinports
# o mac binary -- last time I checked this was a PITA to compile on OS X, the one I have
# is pre-built from some app (can't remember which app). This isn't totally necessary
# (unless it's defined in the py2app's default config file)
#
# FIXME: rewrite or just tie this into build.py
# 
rm -rf dist/hellanzb.app && \
/opt/local/bin/python setup.py py2app && \
cp /opt/local/bin/unrar dist/hellanzb.app/Contents/Resources/ && \
cp /opt/local/bin/par2 dist/hellanzb.app/Contents/Resources/ && \
cp /opt/local/bin/flac dist/hellanzb.app/Contents/Resources/ && \
cp /opt/local/bin/shorten dist/hellanzb.app/Contents/Resources/ && \
cp /usr/local/bin/mac dist/hellanzb.app/Contents/Resources/
