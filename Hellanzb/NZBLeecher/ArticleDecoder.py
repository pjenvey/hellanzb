"""

ArticleDecoder - Decode and assemble files from usenet articles (nzbSegments)

(c) Copyright 2005 Philip Jenvey
[See end of file]
"""
import binascii, os, re, shutil, string, time, Hellanzb
from threading import Lock
from twisted.internet import reactor
from zlib import crc32
from Hellanzb.Daemon import handleNZBDone, pauseCurrent
from Hellanzb.Log import *
from Hellanzb.Logging import prettyException
from Hellanzb.Util import BUF_SIZE, checkShutdown, isHellaTemp, nuke, touch, \
    OutOfDiskSpace
from Hellanzb.NZBLeecher.DupeHandler import handleDupeNZBFile, handleDupeNZBSegment
if Hellanzb.HAVE_C_YENC: import _yenc

__id__ = '$Id$'

# Decode types enum
UNKNOWN, YENCODE, UUENCODE = range(3)

def decode(segment):
    """ Decode the NZBSegment's articleData to it's destination. Toggle the NZBSegment
    instance as having been decoded, then assemble all the segments together if all their
    decoded segment filenames exist """
    encoding = UNKNOWN
    try:
        segment.loadArticleDataFromDisk()
        encoding = decodeArticleData(segment)
        
    except OutOfDiskSpace:
        # Ran out of disk space and the download was paused! Easiest way out of this
        # sticky situation is to requeue the segment
        nuke(segment.getDestination())
        segment.nzbFile.totalReadBytes -= segment.bytes
        segment.nzbFile.nzb.totalReadBytes -= segment.bytes
        reactor.callFromThread(Hellanzb.queue.put, (segment.priority, segment))
        return
    except Exception, e:
        if handleCanceledSegment(segment):
            # Cancelled NZBs could potentially cause IOErrors during writes -- just handle
            # cleanup and return
            return

        error(segment.nzbFile.showFilename + ' segment: ' + str(segment.number) + \
              ' a problem occurred during decoding', e)
        touch(segment.getDestination())

    if Hellanzb.SMART_PAR and segment.isFirstSegment():
        # This will dequeue all of this segment's sibling segments that are still in the
        # NZBSegmentQueue. Segments that aren't in the queue are either:
        # o already decoded and on disk
        # o currently downloading
        # Segments currently downloading are left in segment.nzbFile.todoNzbSegments
        segment.smartDequeue()
    
    Hellanzb.queue.segmentDone(segment)
    if Hellanzb.DEBUG_MODE_ENABLED:
        # FIXME: need a better enum
        if encoding == 1:
            encodingName = 'YENC'
        elif encoding == 2:
            encodingName = 'UUENCODE'
        else:
            encodingName = 'UNKNOWN'
        debug('Decoded (encoding: %s): %s' % (encodingName, segment.getDestination()))

    if handleCanceledSegment(segment):
        return

    if Hellanzb.SMART_PAR and segment.isFirstSegment() and \
            segment.nzbFile.nzb.firstSegmentsDownloaded == len(segment.nzbFile.nzb.nzbFiles):
        # Done downloading all first segments. Check for a few special situations that
        # warrant requeueing of files
        segment.nzbFile.nzb.smartRequeue()
        segment.nzbFile.nzb.logSkippedPars()

    tryAssemble(segment.nzbFile)

def tryAssemble(nzbFile):
    """ Assemble the specified NZBFile if all its segments have been downloaded """
    if nzbFile.isAllSegmentsDecoded():
        try:
            assembleNZBFile(nzbFile)
            # NOTE: exceptions here might cause Hellanzb.queue.fileDone() to not be
            # called
        except OutOfDiskSpace:
            # Delete the partially assembled file. It will be re-assembled later when the
            # downloader becomes unpaused
            nuke(nzbFile.getDestination())
            nzbFile.interruptedAssembly = True
        except SystemExit, se:
            # checkShutdown() throws this, let the thread die
            pass
        except Exception, e:
            # Cancelled NZBs could potentially cause IOErrors during writes -- just handle
            # cleanup and return
            if not handleCanceledFile(nzbFile):
                raise
    elif nzbFile.isSkippedPar and not len(nzbFile.todoNzbSegments):
        # This skipped par file is done and didn't assemble, so manually tell the
        # NZBSegmentQueue that it's finished
        Hellanzb.queue.fileDone(nzbFile)
        
        # It's possible that it was the final decode() called for this NZB
        tryFinishNZB(nzbFile.nzb)

def nuke(f):
    try:
        os.remove(f)
    except Exception, e:
        pass

def handleCanceledSegment(nzbSegment): 
    """ Return whether or not the specified NZBSegment has been canceled. If so, delete its
    associated decoded file on disk, if it exists """
    if nzbSegment.nzbFile.nzb.isCanceled():
        nuke(nzbSegment.getDestination())
        return True
    return False

def handleCanceledFile(nzbFile):
    """ Return whether or not the specified NZBFile has been canceled. If so, delete its
    associated decoded file on disk, if it exists """
    if nzbFile.nzb.isCanceled():
        nuke(nzbFile.getDestination())
        return True
    return False

MIME_HEADER_RE = re.compile('^(\w|-)+: .*$')
def stripArticleData(articleData):
    """ Rip off leading/trailing whitespace (and EOM char) from the articleData list """
    try:
        # Rip off the leading whitespace
        while articleData[0] == '' or MIME_HEADER_RE.match(articleData[0]):
            articleData.pop(0)

        # and trailing
        while articleData[-1] == '':
            articleData.pop(-1)

        # Remove the EOM char
        if articleData[-1] == '..' or articleData[-1] == '.':
            articleData.pop(-1)
            
            # and trailing again
            while articleData[-1] == '':
                articleData.pop(-1)
            
    except IndexError:
        pass

def yInt(object, message = None):
    """ Helper function for casting yEncode keywords to integers """
    try:
        return int(object)
    except ValueError:
        if message is not None:
            error(message)
        return None

def parseArticleData(segment, justExtractFilename = False):
    """ Clean the specified segment's articleData, and get the article's filename from the
    articleData. If not justExtractFilename, also decode the articleData to the segment's
    destination """
    if segment.articleData is None:
        raise FatalError('Could not getFilenameFromArticleData')

    # First, clean it
    stripArticleData(segment.articleData)

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
        if not withinData and line.startswith('=ybegin'):
            # See if we can parse the =ybegin line
            ybegin = ySplit(line)
            
            if not ('line' in ybegin and 'size' in ybegin and 'name' in ybegin):
                # FIXME: show filename information
                raise FatalError('* Invalid =ybegin line in part %d!' % segment.number)

            setRealFileName(segment.nzbFile, ybegin['name'],
                            settingSegmentNumber = segment.number)
            if segment.nzbFile.ySize is None:
                    segment.nzbFile.ySize = yInt(ybegin['size'],
                                                  '* Invalid =ybegin line in part %d!' % segment.number)
                    
            encodingType = YENCODE

        elif not withinData and line.startswith('=ypart'):
            # ybegin doesn't ensure a ypart on the next line
            withinData = True

            ypart = ySplit(line)
            if 'begin' in ypart:
                segment.yBegin = yInt(ypart['begin'])
            if 'end' in ypart:
                segment.yEnd = yInt(ypart['end'])

            # Just incase a bad post doesn't include a begin header, ensure
            # the correct encodingType
            encodingType = YENCODE

        elif withinData and line.startswith('=yend'):
            yend = ySplit(line)
            if 'size' in yend:
                segment.ySize = yInt(yend['size'])
            if 'pcrc32' in yend:
                segment.yCrc = '0' * (8 - len(yend['pcrc32'])) + yend['pcrc32'].upper()
            elif 'crc32' in yend and yend.get('part', '1') == '1':
                segment.yCrc = '0' * (8 - len(yend['crc32'])) + yend['crc32'].upper()

        elif not withinData and line.startswith('begin '):
            filename = line.rstrip().split(' ', 2)[2]
            if not filename:
                # FIXME: show filename information
                raise FatalError('* Invalid begin line in part %d!' % segment.number)
            setRealFileName(segment.nzbFile, filename,
                            settingSegmentNumber = segment.number)
            encodingType = UUENCODE
            withinData = True

        elif not withinData and encodingType == YENCODE:
            # Found ybegin, but no ypart. withinData should have started on the previous
            # line -- so instead we have to process the current line
            withinData = True

            # un-double-dot any lines :\
            if line[:2] == '..':
                line = line[1:]
                segment.articleData[index] = line

        elif not withinData and segment.number == 1:
            # Assume segment #1 has a valid header -- continue until we find it. I've seen
            # some UUEncoded archives start like this:
            #
            # 222 423850423 <PLSmfijf.803495116$Es4.92395@feung.shui.beek.dk> body
            # BSD.ARCHIVE HERE IT IS
            # begin 644 bsd-archive.part45.rar
            # MJ"D+D:J6@1L'J0[O;JXTO/V`HR]4JO:/Q\J$M79S9("@]^]MFIGW/\`VJJC_
            #
            # (and of course, only segment #1 actually contains a filename). The UUDecode
            # function will also quietly ignore the first couple of lines if they are
            # garbage (can't decode)
            continue

        elif not withinData:
            # Assume this is a subsequent uuencode segment
            withinData = True
            encodingType = UUENCODE

    # FIXME: could put this check even higher up
    if justExtractFilename:
        return

    encodingType = decodeSegmentToFile(segment, encodingType)
    del segment.articleData
    segment.articleData = '' # We often check it for is None
    return encodingType
decodeArticleData=parseArticleData

def setRealFileName(nzbFile, filename, forceChange = False, settingSegmentNumber = None):
    """ Set the actual filename of the segment's parent nzbFile. If the filename wasn't
    already previously set, set the actual filename atomically and also atomically rename
    known temporary files belonging to that nzbFile to use the new real filename """
    # FIXME: remove locking. actually, this function really needs to be locking when
    # nzb.destDir is changing (when the archive dir is moved around)
    switchedReal = False
    if nzbFile.filename is not None and nzbFile.filename != filename and \
            not isHellaTemp(nzbFile.filename):
        # This NZBFile already had a real filename set, and now something has triggered it
        # be changed
        switchedReal = True

        if forceChange:
            # Force change -- this segment has been found to be a duplicate and needs to
            # be renamed (but its parent NZBFile is currently being downloaded)
            nzbFile.forcedChangedFilename = True
        else:
            # Not a force change. Either ignore the supposed new real filename (we already
            # had one, we're just going to stick with it) and print an error about
            # receiving bad header data. Or if this NZBFile filename mismatches because it
            # was previously found to be a dupe (and its filename was renamed) just
            # completely ignore the new filename
            if not nzbFile.forcedChangedFilename:
                segmentInfo = ''
                if settingSegmentNumber is not None:
                    segmentInfo = ' segment: %i' % settingSegmentNumber
                    
                error(nzbFile.showFilename + segmentInfo + \
                      ' has incorrect filename header!: ' + filename + ' should be: ' + \
                      nzbFile.showFilename)
            return
    elif nzbFile.filename == filename:
        return
     
    # We might have been using a tempFileName previously, and just succesfully found
    # the real filename in the articleData. Immediately rename any files that were
    # using the temp name
    nzbFile.tempFileNameLock.acquire()
    renameFilenames = {}

    if switchedReal:
        notOnDisk = nzbFile.todoNzbSegments.union(nzbFile.dequeuedSegments)
        # Get the original segment filenames via getDestination() (before we change it)
        renameSegments = [(nzbSegment, nzbSegment.getDestination()) for nzbSegment in
                           nzbFile.nzbSegments if nzbSegment not in notOnDisk]

    # Change the filename
    nzbFile.filename = filename

    if switchedReal:
        # Now get the new filenames via getDestination()
        for (renameSegment, oldName) in renameSegments:
            renameFilenames[os.path.basename(oldName)] = \
                os.path.basename(renameSegment.getDestination())

    # We also need a mapping of temp filenames to the new filename, incase we just found
    # the real file name (filename is None or filename was previously set to a temp name)
    for nzbSegment in nzbFile.nzbSegments:
        renameFilenames[nzbSegment.getTempFileName()] = \
            os.path.basename(nzbSegment.getDestination())
                          
    # Rename all segments
    for file in os.listdir(nzbFile.nzb.destDir):
        if file in renameFilenames:
            orig = nzbFile.nzb.destDir + os.sep + file
            new = nzbFile.nzb.destDir + os.sep + renameFilenames.get(file)
            shutil.move(orig, new)

            # Keep the onDiskSegments map in sync
            if Hellanzb.queue.onDiskSegments.has_key(orig):
                Hellanzb.queue.onDiskSegments[new] = \
                    Hellanzb.queue.onDiskSegments.pop(orig)

    nzbFile.tempFileNameLock.release()

def yDecodeCRCCheck(segment, decoded):
    """ Validate the CRC of the segment with the yencode keyword """
    passedCRC = False
    if segment.yCrc is None:
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
    if segment.ySize is not None and size != segment.ySize:
        message = segment.nzbFile.showFilename + ' segment ' + str(segment.number) + \
            ': file size mismatch: actual: ' + str(size) + ' != ' + str(segment.ySize) + ' (expected)'
        warn(message)

def handleIOError(ioe):
    if ioe.errno == 28:
        if not Hellanzb.downloadPaused:
            error('No space left on device!')
            pauseCurrent()
            growlNotify('Error', 'hellanzb Download Paused', 'No space left on device!', True)
        raise OutOfDiskSpace('LOL BURN SOME DVDS LOL')
    else:
        debug('handleIOError: got: %s' % str(ioe))
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
            
            # CRC check. FIXME: use yDecodeCRCCheck for this!
            if segment.yCrc is None:
                passedCRC = False
                # FIXME: I've seen CRC errors at the end of archive cause logNow = True to
                # print I think after handleNZBDone appends a newline (looks like crap)
                error(segment.nzbFile.showFilename + ' segment: ' + str(segment.number) + \
                      ' does not have a valid CRC/yend line!')
            else:
                crc = '%08X' % ((crc ^ -1) & 2**32L - 1)
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

        # Handle dupes if they exist
        handleDupeNZBSegment(segment)
        if handleCanceledSegment(segment):
            return YENCODE
        
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

        return YENCODE

    elif encodingType == UUENCODE:
        decodedLines = []
        try:
            decodedLines = UUDecode(segment.articleData)
        except binascii.Error, msg:
            error('UUDecode failed in file: %s (part number: %d) error: %s' % \
                  (segment.getDestination(), segment.number, msg))
            debug('UUDecode failed in file: %s (part number: %d) error: %s' % \
                  (segment.getDestination(), segment.number, prettyException(msg)))

        handleDupeNZBSegment(segment)
        if handleCanceledSegment(segment):
            return UUENCODE
        
        # Write the decoded segment to disk
        writeLines(segment.getDestination(), decodedLines)

        return UUENCODE

    elif segment.articleData == '':
        if Hellanzb.DEBUG_MODE_ENABLED:
            debug('NO articleData, touching file: ' + segment.getDestination())

        handleDupeNZBSegment(segment)
        if handleCanceledSegment(segment):
            return UNKNOWN

        touch(segment.getDestination())

    else:
        # FIXME: should this be an info instead of debug? Should probably change the
        # above: articleData == '' check to articleData.strip() == ''. that block would
        # cover all null articleData and would be safer to always info() about
        if Hellanzb.DEBUG_MODE_ENABLED:
            debug('Mysterious data, did not YY/UDecode!! Touching file: ' + \
                  segment.getDestination())

        handleDupeNZBSegment(segment)
        if handleCanceledSegment(segment):
            return UNKNOWN

        touch(segment.getDestination())

    return UNKNOWN

# Build the yEnc decode table
YDEC_TRANS = ''.join([chr((i + 256 - 42) % 256) for i in range(256)])
def yDecode(dataList):
    buffer = []
    index = -1
    for line in dataList:
       if index <= 5 and (line[:7] == '=ybegin' or line[:6] == '=ypart'):
           continue
       elif line[:5] == '=yend':
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

    # All whitespace and EOMs (.) should be stripped from the end at this point. Now,
    # strip the uuencode 'end' string and or whitespace (including grave accents) until we
    # have nothing but uuencoded data and its headers
    if dataList[-1][:3] == 'end':
        dataList.pop(-1)
    while dataList[-1] == '' or dataList[-1] == '`':
        dataList.pop(-1)

    # Any line before this index should precede with 'M'
    notMLines = len(dataList) - 1

    index = -1
    for line in dataList:
        index += 1

        if (index <= 5 and line[:6] == 'begin ') or \
                (index < notMLines and line[:1] != 'M'):
            notMLines -= 1
            continue

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

    # don't overwrite existing files -- instead rename them to 'file_dupeX' if they exist
    handleDupeNZBFile(nzbFile)
    if handleCanceledFile(nzbFile):
        return

    file = open(nzbFile.getDestination(), 'wb')
    write = file.write

    # Sort the segments incase they were out of order in the NZB file
    toAssembleSegments = nzbFile.nzbSegments[:]
    toAssembleSegments.sort(lambda x, y : cmp(x.number, y.number))
    
    for nzbSegment in toAssembleSegments:
        decodedSegmentFile = open(nzbSegment.getDestination(), 'rb')
        read = decodedSegmentFile.read
        try:
            while True:
                buf = read(BUF_SIZE)
                if not buf:
                    break
                write(buf)

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
    for nzbSegment in toAssembleSegments:
        try:
            os.remove(nzbSegment.getDestination())
        except OSError, ose:
            # postponement might have moved the file we just wrote to:
            # exceptions.OSError: [Errno 2] No such file or directory: 
            if ose.errno != 2:
                debug('Unexpected ERROR while removing segmentFile: ' + segmentFile)

    Hellanzb.queue.fileDone(nzbFile)
    reactor.callFromThread(fileDone)
    
    debug('Assembled file: ' + nzbFile.getDestination() + ' from segment files: ' + \
          str([nzbSegment.getDestination() for nzbSegment in toAssembleSegments]))

    # nudge gc
    for nzbSegment in nzbFile.nzbSegments:
        del nzbSegment.nzbFile
        del nzbSegment
    del nzbFile.nzbSegments
    
    if autoFinish and not handleCanceledFile(nzbFile):
        # After assembling a file, check the contents of the filesystem to determine if we're done 
        tryFinishNZB(nzbFile.nzb)

def fileDone():
    Hellanzb.totalFilesDownloaded += 1

def tryFinishNZB(nzb):
    """ Determine if the NZB download/decode process is done for the specified NZB -- if it's
    done, trigger handleNZBDone. We'll call this check everytime we finish processing an
    nzbFile """
    #start = time.time()
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
        if nzbFile not in nzb.nzbFiles:
            continue
        
        debug('tryFinishNZB: NOT DONE: ' + nzbFile.getDestination())
        done = False
        break

    if done:
        Hellanzb.queue.nzbDone(nzb)
        debug('tryFinishNZB: finished downloading NZB: ' + nzb.archiveName)
        
        reactor.callFromThread(handleNZBDone, nzb)
        
    #finish = time.time() - start
    #debug('tryFinishNZB (' + str(done) + ') took: ' + str(finish) + ' seconds')
    return done
        
"""
Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:
1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
3. The name of the author or contributors may not be used to endorse or
   promote products derived from this software without specific prior
   written permission.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.

$Id$
"""
