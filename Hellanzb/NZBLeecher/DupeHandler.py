#!/usr/bin/env python
"""

DupeHandler - Functions for handling duplicate files in NZBs. Some NZBs contain multiple
files with the exact same filename (due to a mistake during creation of the archive itself
or the archive's NZB)

Dupe files encountered during the download process (either in NZBFile or NZBSegment form)
will be renamed

Duplicate files detected on disk during parsing of the NZB will be correctly matched up to
their representation in the NZB xml (that is, the according NZBModel objects). This can be
a tricky process, but necessary to safely determine which dupes actually need to be
downloaded

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import os, Hellanzb, ArticleDecoder
from Hellanzb.Log import *
from Hellanzb.Util import dupeName, getFileExtension, nextDupeName, DUPE_SUFFIX_RE

__id__ = '$Id$'

def knownRealNZBFilenames():
    """ Return a list of all known real filenames for every NZBFile in the currently
    downloading NZB """
    filenames = []
    for nzb in Hellanzb.queue.nzbs:
        for nzbFile in nzb.nzbFileElements:
            if nzbFile.filename != None:
                filenames.append(nzb.destDir + os.sep + nzbFile.filename)
    return filenames

def handleDupeNZBSegment(nzbSegment):
    """ Handle a duplicate NZBSegment file on disk (prior to writing a new one), if one exists
    """
    dest = nzbSegment.getDestination()
    if os.path.exists(dest):
        # We have lazily found a duplicate segment (a .segmentXXXX already on disk that we
        # were about to write to). Determine the new, duplicate filename, that either the
        # on disk file or the segment ABOUT to be written to disk will be renamed to. We
        # must avoid renaming it a filename already on disk (nextDupeName will check on
        # disk for us) OR to an already reserved filename that may not already be on disk
        # (represented by eschewNames)
        parentFilename = dest[:-12] # remove .segmentXXXX
        segmentNumStr = dest[-12:] # just .segmentXXXX
        dupeNZBFileName = nextDupeName(parentFilename, eschewNames = knownRealNZBFilenames())

        beingDownloadedNZBSegment = Hellanzb.queue.isBeingDownloadedFile(dest)

        info('Duplicate segment (%s), renaming parent file: %s to %s' % \
             (segmentNumStr, os.path.basename(parentFilename),
              os.path.basename(dupeNZBFileName)))
        
        if beingDownloadedNZBSegment is not None:
            debug('handleDupeNZBSegment: handling dupe: %s' % os.path.basename(dest))
            
            # Maintain the correct order when renaming -- the earliest (as they appear in
            # the NZB) clashing NZBFile gets renamed
            if beingDownloadedNZBSegment.nzbFile.number < nzbSegment.nzbFile.number:
                renameFile = beingDownloadedNZBSegment.nzbFile
            else:
                renameFile = nzbSegment.nzbFile

            ArticleDecoder.setRealFileName(renameFile, os.path.basename(dupeNZBFileName),
                                           forceChange = True)
        else:
            # NOTE: Probably nothing should trigger this, except maybe .par .segment0001
            # files (when smartpar is added). CAUTION: Other cases that might trigger this
            # block should no longer happen!
            debug('handleDupeNZBSegment: handling dupe (not beingDownloadedNZBSegment!?): %s' % \
                  os.path.basename(dest))
            os.rename(dest, dupeNZBFileName + segmentNumStr)

def handleDupeNZBFile(nzbFile):
    """ Handle a duplicate NZBFile file on disk (prior to writing a new one), if one exists
    """
    dest = nzbFile.getDestination()
    # Ignore .nfo files -- newzbin.com dumps the .nfo file to the end of every nzb (if one
    # exists) -- so it's commonly a dupe. If it's already been downloaded (is an actual
    # fully assembled NZBFile on disk, not an NZBSegment), just overwrite it
    if os.path.exists(dest) and getFileExtension(dest) != 'nfo':
        # Set a new dupeName -- avoid setting a dupeName that is on disk or in the
        # eschewNames (like above in handleDupeNZBSegment)
        dupeNZBFileName = dupeName(dest, eschewNames = knownRealNZBFilenames())
        
        info('Duplicate file, renaming: %s to %s' % (os.path.basename(dest),
                                                     os.path.basename(dupeNZBFileName)))
        debug('handleDupeNZBFile: renaming: %s to %s' % (os.path.basename(dest),
                                                        os.path.basename(dupeNZBFileName)))

        os.rename(dest, dupeNZBFileName)

def handleDupeOnDisk(filename, workingDirDupeMap):
    """ Determine if the specified filename on disk (in the WORKING_DIR) is a duplicate
    file. Simply returns False if that's not the case, otherwise it returns True and takes
    account of the dupe

    Duplicate file information is stored in the workingDirDupeMap, in the format (Given
    the following duplicate files on disk):

    file.rar
    file.rar.hellanzb_dupe0
    file.rar.hellanzb_dupe2

    Would produce:
    
    workingDirDupeMap = { 'file.rar': [
                                       [0, None],
                                       [1, None],
                                       [2, None],
                                       [-1, None]
                                      ]
                        }


    This represents a mapping of the original file (file.rar) to a list containing each
    duplicate file's number and its associated NZBFile object. At this point (just prior
    to parsing of the NZB) the NZBFile object associated with the dupe is not known, so
    this functions leaves it as None. This will be filled in later by
    handleDupeNZBFileNeedsDownload (called from NZBFile.needsDownload)

    The duplicate with index -1 is special -- it represents the origin: 'file.rar'. This
    ordering correlates to how these duplicates were originally written to disk, and the
    order they'll be encountered in the NZB (hence the origin appearing last)

    This represents the full RANGE of files that SHOULD be on disk (that we currently know
    about). The file 'file.rar.hellanzb_dupe1' is missing from disk, but given the fact
    that 'file.rar.hellanzb_dupe2' exists means it WILL be there at some point

    Encountering a file listing like this (missing the dupe_1) is going to be a rare
    occurence but it could happen under the right situations. The point is to avoid even
    these rare situations as they could lead to inconsistent state of the NZB archive (and
    ultimately ugly hellanzb lockups) """
    match = DUPE_SUFFIX_RE.match(filename)
    if not match:
        # Not a dupe
        return False
    
    else:
        # A dupe, ending in the _hellanzb_dupeX suffix
        strippedFilename = match.group(1) # _hellanzb_dupeX suffix removed
        dupeNum = int(match.group(2)) # the X in _hellanzb_dupeX

        newDupeMapping = False
        if not workingDirDupeMap.has_key(strippedFilename):
            newDupeMapping = True
            # A brand new dupe not yet in the map. There must always be an associated file
            # without the _hellanzb_dupeX suffix (branded as index -1)
            
            # This will be a list of (lists with indicies):
            # [0] The dupe number (X of hellanzb_dupeX)
            # [1] The associated dupe's NZBFile (or None if not yet found)
            workingDirDupeMap[strippedFilename] = [[-1, None]]

        dupesForFile = workingDirDupeMap[strippedFilename]
        
        if not newDupeMapping:
            # There are previous entries in our mapping (besides -1). Ensure any missing
            # indicies are filled in
            prevDupeEntry = dupesForFile[-2]
            
            if prevDupeEntry[0] != dupeNum - 1:
                # The last entry is not (current - 1), there are missing indicies
                missingIndex = prevDupeEntry[0]
                while missingIndex < dupeNum - 1:
                    missingIndex += 1
                    dupesForFile.insert(-1, [missingIndex, None])
                
        # Finally add the entry we're dealing with -- the dupe represented by the passed
        # in filename
        dupesForFile.insert(-1, [dupeNum, None])
        
        return True

def handleDupeNZBFileNeedsDownload(nzbFile, workingDirDupeMap):
    """ Determine whether or not this NZBFile is a known duplicate. If so, also determine if
    this NZBFile needs to be downloaded """
    isDupe = False
    # Search the dupes on disk for a match
    for file in workingDirDupeMap.iterkeys():
        if nzbFile.subject.find(file) > -1:
            isDupe = True

            debug('handleDupeNeedsDownload: handling dupe: %s' % file)
            for dupeEntry in workingDirDupeMap[file]:
                # Ok, *sigh* we're a dupe. Find the first unidentified index in the
                # dupeEntry (dupeEntry[1] is None)
                origin = None
                if dupeEntry[1] is None:
                    dupeEntry[1] = nzbFile

                    # Set our filename now, since we know it, for sanity sake
                    dupeFilename = nextDupeName(Hellanzb.WORKING_DIR + os.sep + file,
                                                checkOnDisk = False,
                                                minIteration = dupeEntry[0] + 1)
                    nzbFile.filename = os.path.basename(dupeFilename)
                    debug('handleDupeNeedsDownload: marking fileNum: %i as dupeFilename' \
                          ' %s (dupeEntry index: %i)' % (nzbFile.number, nzbFile.filename,
                                                         dupeEntry[0]))

                    # Now that we have the correct filename we can determine if this dupe
                    # needs to be downloaded
                    if os.path.isfile(dupeFilename):
                        debug('handleDupeNeedsDownload: dupeName: %s needsDownload: False' \
                              % nzbFile.filename)
                        return isDupe, False
                    
                    debug('handleDupeNeedsDownload: dupeName: %s needsDownload: True' \
                          % nzbFile.filename)
                    return isDupe, True

                # Keep track of the origin -- we need to handle it specially (rename it to
                # an actual dupeName ASAP) if there are more duplicates in the NZB than
                # there are currently on disk
                elif dupeEntry[0] == -1:
                    origin = dupeEntry[1]

            if origin is not None and origin.filename is None:
                # That special case -- there are more duplicates in the NZB than there are
                # currently on disk (we looped through all dupeEntries and could not find
                # a match to this NZBFile on disk). Rename the origin immediately. This
                # needs to be done because if the origin's has segments on disk (it's not
                # yet the fully assembled file), these will cause massive trouble later
                # with ArticleDecoder.handleDupeNZBSegment
                renamedOrigin = nextDupeName(Hellanzb.WORKING_DIR + os.sep + file)
                ArticleDecoder.setRealFileName(origin, os.path.basename(renamedOrigin),
                                               forceChange = True)
                debug('handleDupeNeedsDownload: renamed origin from: %s to: %s' \
                      % (file, renamedOrigin))

            # Didn't find a match on disk. Needs to be downloaded
            return isDupe, True
        
    return isDupe, None

"""
/*
 * Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
 * All rights reserved.
 *
 * Redistribution and use in source and binary forms, with or without
 * modification, are permitted provided that the following conditions
 * are met:
 * 1. Redistributions of source code must retain the above copyright
 *    notice, this list of conditions and the following disclaimer.
 * 2. Redistributions in binary form must reproduce the above copyright
 *    notice, this list of conditions and the following disclaimer in the
 *    documentation and/or other materials provided with the distribution.
 * 3. The name of the author or contributors may not be used to endorse or
 *    promote products derived from this software without specific prior
 *    written permission.
 *
 * THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
 * ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 * IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 * ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
 * FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
 * DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
 * OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
 * HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
 * LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
 * OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
 * SUCH DAMAGE.
 *
 * $Id$
 */
"""
