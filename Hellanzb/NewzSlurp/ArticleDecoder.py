import re, string
from zlib import crc32
from Hellanzb.Logging import *
from StringIO import StringIO

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
        pass
    debug('DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDdecoded')

def parseArticleData(segment, justExtractFilename = False):
    """ decode the article (uudecode/ydecode) to the destination """
    # rename if fileDestination exists?
    #s = StringIO(segment.articleData)

    if segment.articleData == None:
        raise FatalError('Could not getFilenameFromArticleData')
    
    #cleanData = StringIO()
    cleanData = []
    isUUDecode = False
    isYDecode = False
    withinData = False
    i = -1
    #articleDataStream = StringIO(segment.articleData)
    #for line in segment.articleData:
    #for line in articleDataStream:
    #for line in segment.articleData.splitlines(True):
    for line in segment.articleData:
        i += 1
        #open('/tmp/doh2', 'ab').write('line: ' + line)
        #if line == '':
        #    debug('BREAK')
        #    break
        #open('/tmp/doh2', 'ab').write('line: ' + line)

        if withinData:
            #if i % 500 == 0:
                #debug('i: ' + str(i))
            #cleanData.write(line)
            
            # un-double-dot any lines :\
            if line[:2] == '..':
                line = line[1:]
                
            cleanData.append(line)

        # FIXME: we won't always see 'begin ' for UU (only the first header segment would
        # contain it) So we should probably check for yEnc, then fall back to uu. BUT we
        # should also take into account non encoded files (like .nfo), which HeadHoncho
        # handles
        #elif line.startswith('=ybegin'):
        if line.startswith('=ybegin'):
            debug('ybegin on line: ' + str(i))
            # See if we can parse the =ybegin line
            ybegin = ySplit(line)
            debug('er: ' + ybegin['name'])
            if not ('line' in ybegin and 'size' in ybegin and 'name' in ybegin):
                #debug('@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@')
                raise FatalError('* Invalid =ybegin line in part %d!' % fileDestination)
                #print 
                #print '==> %s' % repr(nwrap.lines[l])
            if segment.nzbFile.tempFilename != None and justExtractFilename == True:
                segment.nzbFile.tempFileNameLock.acquire()
                segment.nzbFile.filename = ybegin['name']

                # We were using temp name and just found the new filename. Immediately rename
                # any files that were using the temp name
                tempFileNames = {}
                for nzbSegment in segment.nzbFile.nzbSegments:
                    tempFileNames[nzbSegment.getTempFileName()] = nzbSegment.getDestination()
    
                from Hellanzb import WORKING_DIR
                for file in os.listdir(WORKING_DIR):
                    if file in tempFileNames:
                        newDest = tempFileNames.get('file')
                        shutil.move(WORKING_DIR + os.sep + file,
                                    WORKING_DIR + os.sep + newDest)

                segment.nzbFile.tempFileNameLock.release()
            else:
                segment.nzbFile.filename = ybegin['name']
            isYDecode = True

            # Assume there's a ypart on the next line
            #withinData = True
            
            #cleanData.write(line)
        elif line.startswith('=ypart'):
            withinData = True
        elif line.startswith('=yend'):
            yend = ySplit(line)
            if 'pcrc32' in yend:
                segment.crc = '0' * (8 - len(yend['pcrc32'])) + yend['pcrc32'].upper()
            elif 'crc32' in yend and yend.get('part', '1') == '1':
                segment.crc = '0' * (8 - len(yend['crc32'])) + yend['crc32'].upper()            
        elif line.startswith('begin '):
        #else:
            #debug('@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@')
        #    if line.startswith('begin '):
            debug('-&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&')
            segment.nzbFile.filename = line.rstrip().split(' ', 2)[2]
            isUUDecode = True
            withinData = True
            #cleanData.write(line)

    if justExtractFilename:
        return

    if isUUDecode:
        #decodedLines = UUDecode(cleanData.getvalue())
        decodedLines = UUDecode(cleanData)
        #out = open(fileDestination, 'wb')
        out = open(segment.getDestination(), 'wb')
        debug('U##################################################')
        for line in decodedLines:
            out.write(line)
        out.close()
    elif isYDecode:
        #debug('ydecoding line count: ' + str(len(cleanData.readlines())))
        #decodedLines = yDecode(cleanData.getvalue())
        
        decodedLines = yDecode(cleanData)
        #decoded = ''.join(decodedLines)
        #crc = '%08X' % (crc32(decoded) & 2**32L - 1)
        #if crc != segment.crc:
        #    warn('CRC mismatch ' + crc + ' != ' + segment.crc)
        #out = open(fileDestination, 'wb')
        out = open(segment.getDestination(), 'wb')
        #debug('##################################################')
        for line in decodedLines:
            out.write(line)
        #out.write(decodedLines)
        out.close()

        # Get rid of all this data now that we're done with it
        del segment.articleData
        segment.articleData = '' # We often check it for == None
        del decodedLines
        
        debug('Y##################################################')
        #debug('Decoded (yDecode): ' + fileDestination)
    else:
        debug(',,,,,,,,,,,,,,,,,,,,')
        #raise FatalError('doh!')
decodeArticleData=parseArticleData

#def parseArticleData(segment, justReturnFilename = False):
    # can i refactor above loop code into doing this and the above?

#    pass
        
# From effbot.org/zone/yenc-decoder.htm -- does not suffer from yDecodeOLD's bug -pjenvey
yenc42 = string.join(map(lambda x: chr((x-42) & 255), range(256)), '')
yenc64 = string.join(map(lambda x: chr((x-64) & 255), range(256)), '')
def yDecode(dataList):
    #file = StringIO(dataList)
    buffer = []
    #while 1:
    #    line = file.readline()
    for line in dataList:
        #open('/tmp/doh', 'ab').write('line: ' + line)
        if not line or line[:5] == '=yend':
        #if line[:5] == '=yend':
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

    #return ''.join(buffer)
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
    # Decode it
    #file = StringIO(data)
    buffer = []

    #while 1:
    for line in dataList:
    #    line = file.readline()

        if not line or line[:5] == '=yend':
            break

        if line[-2:] == '\r\n':
            line = line[:-2]
        elif line[-1:] in '\r\n':
            line = line[:-1]

        import binascii
        # FIXME: workaround imported from Newsleecher.HeadHoncho, is this necessary?
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

    #return ''.join(buffer)
    return buffer

def assembleNZBFile(nzbFile):
    """ Assemble the final file from all the NZBFile's decoded segments """
    # FIXME: don't overwrite existing files
    #debug('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
    #debug('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
    #debug('file: ' + nzbFile.fileNameGuess)
    #debug('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
    file = open(nzbFile.getDestination(), 'wb')
    for nzbSegment in nzbFile.nzbSegments:

        # FIXME: do i need binary mode to read?
        # FIXME: trying this with binary off throws an exception in the print line
        # below. it does seem like the reading of the segment file is not workign right
        decodedSegmentFile = open(nzbSegment.getDestination(), 'rb')
        debug('asseml : ' + nzbSegment.getDestination())
        for line in decodedSegmentFile.readlines():
            if line == '':
                break

            #print 'file: ' + nzbSegment.nzbFile.fileNameGuess + ' line: ' + line.encode('utf-8')
            # FIXME: someone has to pad the file if we have broken pieces
            file.write(line)
        decodedSegmentFile.close()
        os.remove(nzbSegment.getDestination())

    file.close()

    # FIXME: benchmark this highly lazy check-if-we're-done-yet function
    tryFinishNZB(nzbFile)

def tryFinishNZB(nzbFile):
    """ Try to finish the NZB download process -- by notifying the nzbFileDone listener
    threads (the Ziplick daemon) """
    nzb = nzbFile.nzb
    done = True
    
    # FIXME: benchmark this

    # FIXME: should only look in the queue's list of known files for what to loop
    # through. this function could be in charge of deleting those files from the queue
    # when they're considered done
    for nzbf in nzb.nzbFileElements:
        if not nzbf.isAllSegmentsDecoded():
            done = False
            break

    if done:
        Hellanzb.nzbfileDone.acquire()
        log('DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDone')
        Hellanzb.nzbfileDone.notify()
        Hellanzb.nzbfileDone.release()
