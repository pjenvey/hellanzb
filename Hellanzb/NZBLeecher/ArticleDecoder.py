"""

ArticleDecoder - Decode and assemble files from usenet articles (nzbSegments)

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import binascii, gc, os, re, shutil, string, time, Hellanzb
from threading import Lock
from twisted.internet import reactor
from zlib import crc32
from Hellanzb.Daemon import handleNZBDone, pauseCurrent
from Hellanzb.Log import *
from Hellanzb.Logging import prettyException
from Hellanzb.Util import checkShutdown, touch, OutOfDiskSpace
if Hellanzb.HAVE_C_YENC: import _yenc

__id__ = '$Id$'

# Decode types enum
UNKNOWN, YENCODE, UUENCODE = range(3)

class ArticleAssemblyGCDelay:
    """ Run gc after every 5 files have been downloaded (shouldGC calls) """
    decodeGCDelay = 5
    decodeGCWait = 0
    decodeGCWaitLock = Lock()
    
    def shouldGC():
        should = False
        ArticleAssemblyGCDelay.decodeGCWaitLock.acquire()

        ArticleAssemblyGCDelay.decodeGCWait += 1
        if ArticleAssemblyGCDelay.decodeGCWait >= ArticleAssemblyGCDelay.decodeGCDelay:
            should = True
            ArticleAssemblyGCDelay.decodeGCWait = 0

        ArticleAssemblyGCDelay.decodeGCWaitLock.release()
        return should
    shouldGC = staticmethod(shouldGC)
GCDelay = ArticleAssemblyGCDelay

def decode(segment):
    """ Decode the NZBSegment's articleData to it's destination. Toggle the NZBSegment
    instance as having been decoded, then assemble all the segments together if all their
    decoded segment filenames exist """
    try:
        # downloaded articleData was written to disk by the downloader
        encodedData = open(Hellanzb.DOWNLOAD_TEMP_DIR + os.sep + segment.getTempFileName() + '_ENC')
        # remove crlfs. FIXME: might be quicker to do this during a later loop
        segment.articleData = [line[:-2] for line in encodedData.readlines()]
        encodedData.close()

        # Delete the copy on disk ASAP
        nuke(Hellanzb.DOWNLOAD_TEMP_DIR + os.sep + segment.getTempFileName() + '_ENC')
        
        decodeArticleData(segment)
        
    except OutOfDiskSpace:
        # Ran out of disk space and download was paused! Easiest way out of this sticky
        # situation is to requeue the segment =[
        nuke(segment.getDestination())
        reactor.callFromThread(Hellanzb.queue.put, (segment.priority, segment))
        return
    except Exception, e:
        touch(segment.getDestination())
        error(segment.nzbFile.showFilename + ' segment: ' + str(segment.number) + \
              ' a problem occurred during decoding', e)

    segment.nzbFile.todoNzbSegments.remove(segment) # FIXME: lock????
    Hellanzb.queue.segmentDone(segment)
    debug('Decoded segment: ' + segment.getDestination())

    if handleCanceled(segment):
        return

    if segment.nzbFile.isAllSegmentsDecoded():
        try:
            assembleNZBFile(segment.nzbFile)
            
        except OutOfDiskSpace:
            # Delete the partially assembled file, it will be re-assembled later
            nuke(segment.nzbFile.getDestination())
            
        except SystemExit, se:
            # checkShutdown() throws this, let the thread die
            pass
        
def nuke(f):
    try:
        os.remove(f)
    except Exception, e:
        pass
    
def handleCanceled(segmentOrFile):
    """ if a file has been canceled, delete it """
    from Hellanzb.NZBLeecher.NZBModel import NZBSegment
    if (isinstance(segmentOrFile, NZBSegment) and \
        segmentOrFile.nzbFile.nzb.isCanceled()) or \
        (not isinstance(segmentOrFile, NZBSegment) and \
         segmentOrFile.nzb.isCanceled()):

        nuke(segmentOrFile.getDestination())
        return True
    
    return False
        
def stripArticleData(articleData):
    """ Rip off leading/trailing whitespace from the articleData list """
    try:
        # Only rip off the first leading whitespace
        while articleData[0] == '':
            articleData.pop(0)

        # Trailing
        while articleData[-1] == '':
            articleData.pop(-1)
    except IndexError:
        pass

def yInt(object, message = None):
    """ Helper function for casting yEncode keywords to integers """
    try:
        return int(object)
    except ValueError:
        if messsage != None:
            error(message)
        return None

def parseArticleData(segment, justExtractFilename = False):
    """ get the article's filename from the articleData. if justExtractFilename == False,
    continue parsing the articleData -- decode that articleData (uudecode/ydecode) to the
    segment's destination """
    # FIXME: rename if fileDestination exists? what to do w /existing files?

    if segment.articleData == None:
        raise FatalError('Could not getFilenameFromArticleData')

    # First, clean it
    stripArticleData(segment.articleData)

    cleanData = []
    encodingType = UNKNOWN
    withinData = False
    index = -1
    for line in segment.articleData:
        index += 1

        if withinData:
            # un-double-dot any lines :\
            if line[:2] == '..':
                line = line[1:]
                segment.articleData[index] = line

        # After stripping the articleData, we should find a yencode header, uuencode
        # header, or a uuencode part header (an empty line)
        if line.startswith('=ybegin'):
            # See if we can parse the =ybegin line
            ybegin = ySplit(line)
            
            if not ('line' in ybegin and 'size' in ybegin and 'name' in ybegin):
                # FIXME: show filename information
                raise FatalError('* Invalid =ybegin line in part %d!' % segment.number)

            setRealFileName(segment, ybegin['name'])
            if segment.nzbFile.ySize == None:
                    segment.nzbFile.ySize = yInt(ybegin['size'],
                                                  '* Invalid =ybegin line in part %d!' % segment.number)
                    
            encodingType = YENCODE

        elif line.startswith('=ypart'):
            # ybegin doesn't ensure a ypart on the next line
            withinData = True

            ypart = ySplit(line)
            if 'begin' in ypart:
                segment.yBegin = yInt(ypart['begin'])
            if 'end' in ypart:
                segment.yEnd = yInt(ypart['end'])
            
        elif line.startswith('=yend'):
            yend = ySplit(line)
            if 'size' in yend:
                segment.ySize = yInt(yend['size'])
            if 'pcrc32' in yend:
                segment.yCrc = '0' * (8 - len(yend['pcrc32'])) + yend['pcrc32'].upper()
            elif 'crc32' in yend and yend.get('part', '1') == '1':
                segment.yCrc = '0' * (8 - len(yend['crc32'])) + yend['crc32'].upper()

        elif line.startswith('begin '):
            filename = line.rstrip().split(' ', 2)[2]
            if not filename:
                # FIXME: show filename information
                raise FatalError('* Invalid begin line in part %d!' % segment.number)
            setRealFileName(segment, filename)
            encodingType = UUENCODE
            withinData = True

        elif line == '':
            continue

        elif not withinData and encodingType == YENCODE:
            # Found ybegin, but no ypart. withinData should have started on the previous
            # line -- so instead we have to process the current line
            withinData = True

            # un-double-dot any lines :\
            if line[:2] == '..':
                line = line[1:]
                segment.articleData[index] = line

        elif not withinData:
            # Assume this is a subsequent uuencode segment
            withinData = True
            encodingType = UUENCODE

    # FIXME: could put this check even higher up
    if justExtractFilename:
        return

    decodeSegmentToFile(segment, encodingType)
    del cleanData
    del segment.articleData
    segment.articleData = '' # We often check it for == None
decodeArticleData=parseArticleData

def setRealFileName(segment, filename):
    """ Set the actual filename of the segment's parent nzbFile. If the filename wasn't
    already previously set, set the actual filename atomically and also atomically rename
    known temporary files belonging to that nzbFile to use the new real filename """
    if segment.nzbFile.filename == None:
        # We might have been using a tempFileName previously, and just succesfully found
        # the real filename in the articleData. Immediately rename any files that were
        # using the temp name
        segment.nzbFile.tempFileNameLock.acquire()
        segment.nzbFile.filename = filename
        # do we really have to lock for this entire operation?

        tempFileNames = {}
        for nzbSegment in segment.nzbFile.nzbSegments:
            tempFileNames[nzbSegment.getTempFileName()] = os.path.basename(nzbSegment.getDestination())

        from Hellanzb import WORKING_DIR
        for file in os.listdir(WORKING_DIR):
            if file in tempFileNames:
                newDest = tempFileNames.get(file)
                shutil.move(WORKING_DIR + os.sep + file,
                            WORKING_DIR + os.sep + newDest)

        segment.nzbFile.tempFileNameLock.release()
    elif segment.nzbFile.filename != filename:
        error(segment.nzbFile.showFilename + ' segment: ' + str(segment.number) + \
              ' has incorrect filename header!: ' + filename + ' should be: ' + \
              segment.nzbFile.showFilename)

def yDecodeCRCCheck(segment, decoded):
    """ Validate the CRC of the segment with the yencode keyword """
    passedCRC = False
    if segment.yCrc == None:
        # FIXME: I've seen CRC errors at the end of archive cause logNow = True to
        # print I think after handleNZBDone appends a newline (looks like crap)
        error(segment.nzbFile.showFilename + ' segment: ' + str(segment.number) + \
              ' does not have a valid CRC/yend line!')
    else:
        crc = '%08X' % (crc32(decoded) & 2**32L - 1)
        
        if crc == segment.yCrc:
            passedCRC = True
        else:
            message = segment.nzbFile.showFilename + ' segment ' + str(segment.number) + \
                ': CRC mismatch ' + crc + ' != ' + segment.yCrc
            error(message)
            
        del decoded
        
    return passedCRC

def yDecodeFileSizeCheck(segment, size):
    """ Ensure the file size from the yencode keyword """
    if segment.ySize != None and size != segment.ySize:
        message = segment.nzbFile.showFilename + ' segment ' + str(segment.number) + \
            ': file size mismatch: actual: ' + str(size) + ' != ' + str(segment.ySize) + ' (expected)'
        warn(message)

def handleIOError(ioe):
    if ioe.errno == 28:
        error('No space left on device!')
        pauseCurrent()
        growlNotify('Error', 'hellanzb Download Paused', 'No space left on device!', True)
        raise OutOfDiskSpace('LOL BURN SOME DVDS LOL')
    else:
        raise
    
def writeLines(dest, lines):
    """ Write the lines out to the destination. Return the size of the file """
    size = 0
    out = open(dest, 'wb')
    try:
        for line in lines:
            size += len(line)
            out.write(line)
            
    except IOError, ioe:
        out.close()
        handleIOError(ioe) # will re-raise
        
    out.close()

    return size
            
def decodeSegmentToFile(segment, encodingType = YENCODE):
    """ Decode the clean data (clean as in it's headers (mime and yenc/uudecode) have been
    removed) list to the specified destination """
    decodedLines = []

    if encodingType == YENCODE:
        if Hellanzb.HAVE_C_YENC:
            decoded, crc, cruft = yDecode(segment.articleData)
            crc = '%08X' % ((crc ^ -1) & 2**32L - 1)
            
            # CRC check
            passedCRC = crc == segment.yCrc
            if not passedCRC:
                message = segment.nzbFile.showFilename + ' segment ' + str(segment.number) + \
                    ': CRC mismatch ' + crc + ' != ' + segment.yCrc
                error(message)
            
        else:
            decoded = yDecode(segment.articleData)

            # CRC check
            passedCRC = yDecodeCRCCheck(segment, decoded)

        # Write the decoded segment to disk
        size = len(decoded)
        out = open(segment.getDestination(), 'wb')
        try:
            out.write(decoded)
        except IOError, ioe:
            out.close()
            handleIOError(ioe) # will re-raise
        out.close()
              
        if passedCRC:
            # File size check vs ydecode header. We only do the file size check if the CRC
            # passed. If the CRC didn't pass the CRC check, the file size check will most
            # likely fail as well, so we skip it
            yDecodeFileSizeCheck(segment, size)

        debug('YDecoded articleData to file: ' + segment.getDestination())

    elif encodingType == UUENCODE:
        try:
            decodedLines = UUDecode(segment.articleData)
        except binascii.Error, msg:
            error('Decode failed in file: %s (part number: %d) error: %s' % \
                  (segment.getDestination(), segment.number, msg))
            debug('Decode failed in file: %s (part number: %d) error: %s' % \
                  (segment.getDestination(), segment.number, prettyException(msg)))

        # Write the decoded segment to disk
        writeLines(segment.getDestination(), decodedLines)

        debug('UUDecoded articleData to file: ' + segment.getDestination())

    elif segment.articleData == '':
        debug('NO articleData, touching file: ' + segment.getDestination())
        touch(segment.getDestination())

    else:
        # FIXME: should this be an info instead of debug? Should probably change the
        # above: articleData == '' check to articleData.strip() == ''. that block would
        # cover all null articleData and would be safer to always info() about
        debug('Mysterious data, did not YY/UDecode!! Touching file: ' + segment.getDestination())
        touch(segment.getDestination())

## This yDecoder is verified to be 100% correct. We have reverted back to our older one,
## though. It had bugs, which seemed to now be fixed. Not 100% sure of that yet though
# From effbot.org/zone/yenc-decoder.htm -- does not suffer from yDecodeOLD's bug -pjenvey
yenc42 = string.join(map(lambda x: chr((x-42) & 255), range(256)), '')
yenc64 = string.join(map(lambda x: chr((x-64) & 255), range(256)), '')
def yDecode_SAFE(dataList):
    """ yDecode the specified list of data, returning results as a list """
    buffer = []
    index = -1
    for line in dataList:
        index += 1
        if index <= 5 and (line[:7] == '=ybegin' or line[:6] == '=ypart'):
            continue
        elif not line or line[:5] == '=yend':
            break

        data = string.split(line, '=')
        buffer.append(string.translate(data[0], yenc42))
        for data in data[1:]:
            if not data:
                #error('Bad yEncoded data, file: %s (part number: %d)' % \
                #      (segment.getDestination(), segment.number))
                continue
            data = string.translate(data, yenc42)
            buffer.append(string.translate(data[0], yenc64))
            buffer.append(data[1:])

    return buffer

# Build the yEnc decode table
YDEC_TRANS = ''.join([chr((i + 256 - 42) % 256) for i in range(256)])
def yDecode(dataList):
    buffer = []
    index = -1
    for line in dataList:
       if index <= 5 and (line[:7] == '=ybegin' or line[:6] == '=ypart'):
           continue
       elif not line or line[:5] == '=yend':
           break

       buffer.append(line)

    data = ''.join(buffer)

    if Hellanzb.HAVE_C_YENC:
        return _yenc.decode_string(data)
    
    # unescape NUL, TAB, LF, CR, 'ESC', ' ', ., =
    # NOTE: The yencode standard dictates these characters as 'critical' and are required
    # to be escaped, EXCEPT for the ESCAPE CHAR. It is included here because it has been
    # seen to be escaped by some yencoders. The standard also says that ydecoders should
    # be able to handle decoding ANY character being escaped. I have noticed some
    # yencoders take it upon themselves to escape the ESCAPE CHAR, so we handle it. FIXME:
    # We obviously aren't 'correct' in we only handle unescaping characters we know about
    # (this is faster). This will be as good as it gets for the python yDecoder, the next
    # step in fixing this & optimizing the ydecoder is switching to a C implementation
    # -pjenvey
    for i in (0, 9, 10, 13, 27, 32, 46, 61):
        j = '=%c' % (i + 64)
        data = data.replace(j, chr(i))
        
    return data.translate(YDEC_TRANS)
               
YSPLIT_RE = re.compile(r'(\S+)=')
def ySplit(line):
    """ Split a =y* line into key/value pairs """
    fields = {}
    
    parts = YSPLIT_RE.split(line)[1:]
    if len(parts) % 2:
            return fields
    
    for i in range(0, len(parts), 2):
            key, value = parts[i], parts[i+1]
            fields[key] = value.strip()
    
    return fields

def UUDecode(dataList):
    """ UUDecode the specified list of data, returning results as a list """
    buffer = []

    index = -1
    for line in dataList:
        index += 1

        if index <= 5 and (not line or line[:6] == 'begin '):
            continue
        elif not line or line[:3] == 'end':
            break

        # From pyNewsleecher. Which ripped it from python's uu module (with maybe extra
        # overhead stripped out)
        try:
            data = binascii.a2b_uu(line)
            buffer.append(data)
        except binascii.Error, msg:
            # Workaround for broken uuencoders by /Fredrik Lundh
            try:
                #warn('UUEncode workaround')
                nbytes = (((ord(line[0])-32) & 63) * 4 + 5) / 3
                data = binascii.a2b_uu(line[:nbytes])
                buffer.append(data)
            except binascii.Error, msg:
                debug('UUDecode failed, line: ' + repr(line))
                raise

    return buffer

def assembleNZBFile(nzbFile, autoFinish = True):
    """ Assemble the final file from all the NZBFile's decoded segments """
    # FIXME: does someone has to pad the file if we have broken pieces?
    
    # FIXME: don't overwrite existing files???
    file = open(nzbFile.getDestination(), 'wb')
    segmentFiles = []
    for nzbSegment in nzbFile.nzbSegments:
        segmentFiles.append(nzbSegment.getDestination())

        decodedSegmentFile = open(nzbSegment.getDestination(), 'rb')
        try:
            for line in decodedSegmentFile:
                if line == '':
                    break

                file.write(line)

        except IOError, ioe:
            file.close()
            decodedSegmentFile.close()
            handleIOError(ioe) # will re-raise
                    
        decodedSegmentFile.close()

        # Avoid delaying CTRL-C during this possibly lengthy file assembly loop
        try:
            checkShutdown()

        except SystemExit, se:
            # We were interrupted. Instead of waiting to finish, just delete the file. It
            # will be automatically assembled upon restart
            debug('(CTRL-C) Removing unfinished file: ' + nzbFile.getDestination())
            file.close()
            try:
                os.remove(nzbFile.getDestination())
            except OSError, ose:
                # postponement might have moved the file we just wrote to:
                # exceptions.OSError: [Errno 2] No such file or directory: 
                if ose.errno != 2:
                    debug('Unexpected ERROR while removing nzbFile: ' + nzbFile.getDestination())
            raise

    file.close()
    # Finally, delete all the segment files when finished
    for segmentFile in segmentFiles:
        try:
            os.remove(segmentFile)
        except OSError, ose:
            # postponement might have moved the file we just wrote to:
            # exceptions.OSError: [Errno 2] No such file or directory: 
            if ose.errno != 2:
                debug('Unexpected ERROR while removing segmentFile: ' + segmentFile)
        
    Hellanzb.queue.fileDone(nzbFile)
    reactor.callFromThread(fileDone)
    
    debug('Assembled file: ' + nzbFile.getDestination() + ' from segment files: ' + \
          str([ nzbSegment.getDestination() for nzbSegment in nzbFile.nzbSegments ]))
    
    canceled = handleCanceled(nzbFile)

    # nudge gc
    for nzbSegment in nzbFile.nzbSegments:
        del nzbSegment.nzbFile
        del nzbSegment
    del nzbFile.nzbSegments
    if GCDelay.shouldGC():
        debug('(GCDELAYED) GCING')
        gc.collect()

    if autoFinish and not canceled:
        # After assembling a file, check the contents of the filesystem to determine if we're done 
        tryFinishNZB(nzbFile.nzb)

def fileDone():
    Hellanzb.totalFilesDownloaded += 1

def tryFinishNZB(nzb):
    """ Determine if the NZB download/decode process is done for the specified NZB -- if it's
    done, trigger handleNZBDone. We'll call this check everytime we finish processing an
    nzbFile """
    start = time.time()
    done = True

    # Simply check if there are any more nzbFiles in the queue that belong to this nzb
    Hellanzb.queue.nzbsLock.acquire()
    postponed = False
    if nzb not in Hellanzb.queue.nzbs:
        postponed = True
    Hellanzb.queue.nzbsLock.release()
        
    Hellanzb.queue.nzbFilesLock.acquire()
    if not postponed:
        queueFilesCopy = Hellanzb.queue.nzbFiles.copy()
    else:
        queueFilesCopy = Hellanzb.queue.postponedNzbFiles.copy()
    Hellanzb.queue.nzbFilesLock.release()

    for nzbFile in queueFilesCopy:
        if nzbFile not in nzb.nzbFileElements:
            continue
        
        debug('NOT DONE, file: ' + nzbFile.getDestination())
        done = False
        break

    if done:
        Hellanzb.queue.nzbDone(nzb)
        debug('tryFinishNZB: finished downloading NZB: ' + nzb.archiveName)
        
        # nudge GC
        nzbFileName = nzb.nzbFileName
        for nzbFile in nzb.nzbFileElements:
            del nzbFile.todoNzbSegments
            del nzbFile.nzb
        del nzb.nzbFileElements
        del nzb
        gc.collect()

        reactor.callFromThread(handleNZBDone, nzbFileName)
        
    finish = time.time() - start
    debug('tryFinishNZB (' + str(done) + ') took: ' + str(finish) + ' seconds')
    return done
        
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
