import binascii, re, string
from zlib import crc32
from Hellanzb.Logging import *
from StringIO import StringIO

# Decode types
UNKNOWN = -1
YENCODE = 0
UUENCODE = 1

def decode(segment):
    """ Decode the NZBSegment's articleData to it's destination. Toggle the NZBSegment
    instance as having been decoded, then assemble all the segments together if all their
    decoded segment filenames exist """
    # FIXME: should need to try/ this call?
    # decode the article to disk w/ a tmp file name
    decodeArticleData(segment)

    #del segment.articleData

    if segment.nzbFile.isAllSegmentsDecoded():
        assembleNZBFile(segment.nzbFile)
    debug('Decoded segment: ' + segment.getDestination())

def parseArticleData(segment, justExtractFilename = False):
    """ get the article's filename from the articleData. if justExtractFilename == False,
    continue parsing the articleData -- decode that articleData (uudecode/ydecode) to the
    segment's destination """
    # FIXME: rename if fileDestination exists? what to do w /existing files?

    if segment.articleData == None:
        raise FatalError('Could not getFilenameFromArticleData')
    
    cleanData = []
    decodeType = UNKNOWN
    withinData = False
    for line in segment.articleData:
        
        if withinData:
            # un-double-dot any lines :\
            if line[:2] == '..':
                line = line[1:]
                
            cleanData.append(line)

        # FIXME: we won't always see 'begin ' for UU (only the first header segment would
        # contain it) So we should probably check for yEnc, then fall back to uu. BUT we
        # should also take into account non encoded files (like .nfo), which HeadHoncho
        # handles
        if line.startswith('=ybegin'):
            # See if we can parse the =ybegin line
            ybegin = ySplit(line)
            
            if not ('line' in ybegin and 'size' in ybegin and 'name' in ybegin):
                raise FatalError('* Invalid =ybegin line in part %d!' % fileDestination)

            noFileName = self.filename == None
            # FIXME:? cant check for tempFilename here. if we're resuming, and we didnt
            # rename temp files created by an older hellanzb process, our tempFilename
            # could be None and we wouldnt rename them. is this safe?
            #if segment.nzbFile.tempFilename != None and justExtractFilename == True:
            if noFileName and justExtractFilename == True:
                # We were using temp name and just succesfully found the new filename via
                # ySplit. Immediately rename any files that were using the temp name
                segment.nzbFile.tempFileNameLock.acquire()
                segment.nzbFile.filename = ybegin['name']

                tempFileNames = {}
                for nzbSegment in segment.nzbFile.nzbSegments:
                    tempFileNames[nzbSegment.getTempFileName()] = nzbSegment.getDestination()
    
                from Hellanzb import WORKING_DIR
                for file in os.listdir(WORKING_DIR):
                    if file in tempFileNames:
                        newDest = tempFileNames.get(file)
                        shutil.move(WORKING_DIR + os.sep + file,
                                    WORKING_DIR + os.sep + newDest)

                segment.nzbFile.tempFileNameLock.release()
            else:
                segment.nzbFile.filename = ybegin['name']
            
            decodeType = YENCODE

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
            debug('UUDECODE begin&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&')
            segment.nzbFile.filename = line.rstrip().split(' ', 2)[2]
            decodeType = UUENCODE
            withinData = True

    # FIXME: could put this check even higher up
    if justExtractFilename:
        return

    decodeCleanDataToFile(cleanData, segment.getDestination(), decodeType)
    del cleanData
    del segment.articleData
    segment.articleData = '' # We often check it for == None
decodeArticleData=parseArticleData

def decodeCleanDataToFile(cleanData, destination, decodeType = YENCODE):
    """ Decode the clean data (clean as in it's headers (mime and yenc/uudecode) have been
    removed) list to the specified destination """
    if decodeType == YDECODE:
        #debug('ydecoding line count: ' + str(len(cleanData.readlines())))
        decodedLines = yDecode(cleanData)

        # FIXME: crc check
        #decoded = ''.join(decodedLines)
        #crc = '%08X' % (crc32(decoded) & 2**32L - 1)
        #if crc != segment.crc:
        #    warn('CRC mismatch ' + crc + ' != ' + segment.crc)
        
        out = open(destination, 'wb')
        for line in decodedLines:
            out.write(line)
        out.close()

        # Get rid of all this data now that we're done with it
        debug('YDecoded articleData to file: ' + destination)

    elif decodeType == UUENCODE:
        decodedLines = UUDecode(cleanData)
        out = open(destination, 'wb')
        for line in decodedLines:
            out.write(line)
        out.close()

        # Get rid of all this data now that we're done with it
        debug('UUDecoded articleData to file: ' + destination)
        
    else:
        debug('FIXME: Did not YY/UDecode!!')
        #raise FatalError('doh!')

# From effbot.org/zone/yenc-decoder.htm -- does not suffer from yDecodeOLD's bug -pjenvey
yenc42 = string.join(map(lambda x: chr((x-42) & 255), range(256)), '')
yenc64 = string.join(map(lambda x: chr((x-64) & 255), range(256)), '')
def yDecode(dataList):
    buffer = []
    for line in dataList:
        if not line or line[:5] == '=yend':
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

    for line in dataList:
        #if not line or line[:5] == '=yend':
        if not line:
            break

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
                warn('UUEncode workaround')
                nbytes = (((ord(line[0])-32) & 63) * 4 + 5) / 3
                data = binascii.a2b_uu(line[:nbytes])
                buffer.append(data)
            except binascii.Error, msg:
                print '\n* Decode failed in part %d: %s' % (nwrap._partnum, msg)
                print '=> %s' % (repr(nwrap.lines[i]))

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
        if not nzbFile.isAllSegmentsDecoded():
            done = False
            break

    if done:
        debug('tryFinishNZB: finished donwloading NZB: ' + nzb.archiveName)
        Hellanzb.nzbfileDone.acquire()
        Hellanzb.nzbfileDone.notify()
        Hellanzb.nzbfileDone.release()
        
    finish = time.time() - start
    debug('tryFinishNZB (' + str(done) + ') took: ' + str(finish) + ' seconds')
