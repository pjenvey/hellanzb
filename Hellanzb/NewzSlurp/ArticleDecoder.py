import binascii, os, re, shutil, string
from zlib import crc32
from Hellanzb.Logging import *
from StringIO import StringIO

# Decode types enum
UNKNOWN, YENCODE, UUENCODE = range(3)

def decode(segment):
    """ Decode the NZBSegment's articleData to it's destination. Toggle the NZBSegment
    instance as having been decoded, then assemble all the segments together if all their
    decoded segment filenames exist """
    # FIXME: should need to try/ this call?
    decodeArticleData(segment)

    #del segment.articleData

    # FIXME: maybe call everything below this postProcess. have postProcess called when --
    # during the queue instantiation?
    if segment.nzbFile.isAllSegmentsDecoded():
        assembleNZBFile(segment.nzbFile)
    debug('Decoded segment: ' + segment.getDestination())

def stripArticleData(articleData):
    """ Rip off leading/trailing whitespace from the articleData list """
    try:
        # Only rip off the first leading whitespace
        #while articleData[0] == '':
        if articleData[0] == '':
            articleData.pop(0)

        # Trailing
        while articleData[-1] == '':
            articleData.pop(-1)
    except IndexError:
        pass

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
        #info('index: ' + str(index) + ' line: ' + line)

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
                raise FatalError('* Invalid =ybegin line in part %d!' % 31337)

            setRealFileName(segment, ybegin['name'])
            encodingType = YENCODE

        elif line.startswith('=ypart'):
            # FIXME: does ybegin always ensure a ypart on the next line?
            withinData = True
            
        elif line.startswith('=yend'):
            yend = ySplit(line)
            if 'pcrc32' in yend:
                segment.crc = '0' * (8 - len(yend['pcrc32'])) + yend['pcrc32'].upper()
            elif 'crc32' in yend and yend.get('part', '1') == '1':
                segment.crc = '0' * (8 - len(yend['crc32'])) + yend['crc32'].upper()

        elif line.startswith('begin '):
            #debug('UUDECODE begin&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&')
            filename = line.rstrip().split(' ', 2)[2]
            if not filename:
                raise FatalError('* Invalid =begin line in part %d!' % 31337)
            setRealFileName(segment, filename)
            encodingType = UUENCODE
            withinData = True
        #elif index == 0 and line == '' :
        elif line == '':
            continue
        elif not withinData:
            # Assume this is a subsequent uuencode segment
            withinData = True
            encodingType = UUENCODE

    # FIXME: could put this check even higher up
    if justExtractFilename:
        return

    #info('data: ' + str(segment.articleData))

    decodeSegmentToFile(segment, encodingType)
    del cleanData
    del segment.articleData
    segment.articleData = '' # We often check it for == None
decodeArticleData=parseArticleData

def setRealFileName(segment, filename):
    """ Set the actual filename of the segment's parent nzbFile. If the filename wasn't
    already previously set, set the actual filename atomically and also atomically rename
    known temporary files belonging to that nzbFile to use the new real filename """
    noFileName = segment.nzbFile.filename == None
    if noFileName and segment.number == 1:
        # We might have been using a tempFileName previously, and just succesfully found
        # the real filename in the articleData. Immediately rename any files that were
        # using the temp name
        segment.nzbFile.tempFileNameLock.acquire()
        segment.nzbFile.filename = filename

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
    else:
        segment.nzbFile.filename = filename

def decodeSegmentToFile(segment, encodingType = YENCODE):
    """ Decode the clean data (clean as in it's headers (mime and yenc/uudecode) have been
    removed) list to the specified destination """
    if encodingType == YENCODE:
        #debug('ydecoding line count: ' + str(len(segment.articleData.readlines())))
        decodedLines = yDecode(segment.articleData)

        # FIXME: crc check
        #decoded = ''.join(decodedLines)
        #crc = '%08X' % (crc32(decoded) & 2**32L - 1)
        #if crc != segment.crc:
        #    warn('CRC mismatch ' + crc + ' != ' + segment.crc)
        
        out = open(segment.getDestination(), 'wb')
        for line in decodedLines:
            out.write(line)
        out.close()

        # Get rid of all this data now that we're done with it
        debug('YDecoded articleData to file: ' + segment.getDestination())

    elif encodingType == UUENCODE:
        decodedLines = UUDecode(segment.articleData)
        out = open(segment.getDestination(), 'wb')
        for line in decodedLines:
            out.write(line)
        out.close()

        # Get rid of all this data now that we're done with it
        debug('UUDecoded articleData to file: ' + segment.getDestination())
        
    else:
        debug('FIXME: Did not YY/UDecode!!')
        #raise FatalError('doh!')

# From effbot.org/zone/yenc-decoder.htm -- does not suffer from yDecodeOLD's bug -pjenvey
yenc42 = string.join(map(lambda x: chr((x-42) & 255), range(256)), '')
yenc64 = string.join(map(lambda x: chr((x-64) & 255), range(256)), '')
def yDecode(dataList):
    buffer = []
    index = -1
    for line in dataList:
        index += 1
        if index <= 5 and (line[:7] == '=ybegin' or line[:6] == '=ypart'):
            continue
        elif not line or line[:5] == '=yend':
            break

        if line[-2:] == '\r\n':
            line = line[:-2]
        elif line[-1:] in '\r\n':
            line = line[:-1]

        data = string.split(line, '=')
        buffer.append(string.translate(data[0], yenc42))
        for data in data[1:]:
            data = string.translate(data, yenc42)
            buffer.append(string.translate(data[0], yenc64))
            buffer.append(data[1:])

    return buffer
                                 
YSPLIT_RE = re.compile(r'(\S+)=')
def ySplit(line):
        'Split a =y* line into key/value pairs'
        fields = {}
        
        parts = YSPLIT_RE.split(line)[1:]
        if len(parts) % 2:
                return fields
        
        for i in range(0, len(parts), 2):
                key, value = parts[i], parts[i+1]
                fields[key] = value.strip()
        
        return fields

def UUDecode(dataList):
    buffer = []

    index = -1
    for line in dataList:
        index += 1

        if index <= 5 and (not line or line[:6] == 'begin '):
            continue
        elif not line or line[:3] == 'end':
            break
        
        #if not line or line[:5] == '=yend':

        if line[-2:] == '\r\n':
            line = line[:-2]
        elif line[-1:] in '\r\n':
            line = line[:-1]

        # NOTE: workaround imported from Newsleecher.HeadHoncho, is this necessary?
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
                error('\n* Decode failed in part %d: %s' % (31337, msg))
                error('=> %s' % (repr(line)))
                #print '\n* Decode failed in part %d: %s' % (nwrap._partnum, msg)
                #print '=> %s' % (repr(nwrap.lines[i]))

    return buffer

def assembleNZBFile(nzbFile):
    """ Assemble the final file from all the NZBFile's decoded segments """
    # FIXME: someone has to pad the file if we have broken pieces
    
    # FIXME: don't overwrite existing files???
    file = open(nzbFile.getDestination(), 'wb')
    for nzbSegment in nzbFile.nzbSegments:

        decodedSegmentFile = open(nzbSegment.getDestination(), 'rb')
        for line in decodedSegmentFile.readlines():
            if line == '':
                break

            file.write(line)
        decodedSegmentFile.close()
        
        os.remove(nzbSegment.getDestination())

    file.close()
    # FIXME: could tell the queue hte file is done here
    #Hellanzb.queue
    debug('Assembled file: ' + nzbFile.getDestination() + ' from segment files: ' + \
          str([ nzbSegment.getDestination() for nzbSegment in nzbFile.nzbSegments ]))

    # After assembling a file, check the contents of the filesystem to determine if we're done 
    tryFinishNZB(nzbFile.nzb)

def tryFinishNZB(nzb):
    """ Determine if the NZB download/decode process is done for the specified NZB -- if it's
    done, notify the nzbFileDone listener threads (the Ziplick daemon). We'll call this
    check everytime we finish processing an nzbFile """
    start = time.time()
    done = True

    # FIXME: should only look in the queue's list of known files for what to loop
    # through. this function could be in charge of deleting those files from the queue
    # when they're considered done
    for nzbFile in nzb.nzbFileElements:
        #if not nzbFile.isAllSegmentsDecoded():
        #if not nzbFile.isAssembled():
        if nzbFile.needsDownload():
            debug('NOT DONE, file: ' + nzbFile.getDestination())
            done = False
            break

    if done:
        debug('tryFinishNZB: finished donwloading NZB: ' + nzb.archiveName)
        Hellanzb.nzbfileDone.acquire()
        Hellanzb.nzbfileDone.notify()
        Hellanzb.nzbfileDone.release()
        
    finish = time.time() - start
    debug('tryFinishNZB (' + str(done) + ') took: ' + str(finish) + ' seconds')
    return done
