import re, string
from Hellanzb.Logging import *
from StringIO import StringIO

def decode(segment):
    """ Decode the NZBSegment's articleData to it's destination. Toggle the NZBSegment
    instance as having been decoded, then assemble all the segments together if all their
    decoded segment filenames exist """

    # FIXME: should need to try/ this call?
    # decode the article to disk w/ a tmp file name
    #decodeArticleData(segment.articleData, segment.getDestination())
    decodeArticleData(segment)

    #del segment.articleData

    if segment.nzbFile.isAllSegmentsDecoded():
        # FIXME:
        assembleNZBFile(segment.nzbFile)
        #pass

#def decodeArticleData(articleData, fileDestination):
#def decodeArticleData(segment):
def parseArticleData(segment, justExtractFilename = False):
    """ decode the article (uudecode/ydecode) to the destination """
    # rename if fileDestination exists?
    #s = StringIO(segment.articleData)

    if segment.articleData == None:
        raise FatalError('Could not getFilenameFromArticleData')
    
    cleanData = StringIO()
    isUUDecode = False
    isYDecode = False
    withinData = False
    i = -1
    for line in segment.articleData:
        i += 1
        if line == '':
            break

        if withinData:
            #if i % 500 == 0:
                #info('i: ' + str(i))
            cleanData.write(line)

        # FIXME: we won't always see 'begin ' for UU (only the first header segment would
        # contain it) So we should probably check for yEnc, then fall back to uu. BUT we
        # should also take into account non encoded files (like .nfo), which HeadHoncho
        # handles
        #elif line.startswith('=ybegin'):
        if line.startswith('=ybegin'):
            info('ybegin on line: ' + str(i))
            # See if we can parse the =ybegin line
            ybegin = ySplit(line)
            info('er: ' + ybegin['name'])
            if not ('line' in ybegin and 'size' in ybegin and 'name' in ybegin):
                #info('@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@')
                raise FatalError('* Invalid =ybegin line in part %d!' % fileDestination)
                #print 
                #print '==> %s' % repr(nwrap.lines[l])
            segment.nzbFile.filename = name
            isYDecode = True
            withinData = True
            #cleanData.write(line)
        #elif line.startswith('begin '):
        else:
            #info('@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@')
            if line.startswith('begin '):
                info('-&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&&')
                segment.nzbFile.filename = line.rstrip().split(' ', 2)[2]
                isUUDecode = True
                withinData = True
            #cleanData.write(line)

    if justExtractFilename:
        return

    if isUUDecode:
        decodedLines = UUDecode(cleanData.getvalue())
        #out = open(fileDestination, 'wb')
        out = open(segment.getDestination(), 'wb')
        info('##################################################')
        for line in decodedLines:
            out.write(line)
        out.close()
    elif isYDecode:
        #info('ydecoding line count: ' + str(len(cleanData.readlines())))
        decodedLines = yDecode(cleanData.getvalue())
        #out = open(fileDestination, 'wb')
        out = open(segment.getDestination(), 'wb')
        #info('##################################################')
        for line in decodedLines:
            out.write(line)
        out.close()
        info('##################################################')
        #info('Decoded (yDecode): ' + fileDestination)
    else:
        info(',,,,,,,,,,,,,,,,,,,,')
        #raise FatalError('doh!')
decodeArticleData=parseArticleData

#def parseArticleData(segment, justReturnFilename = False):
    # can i refactor above loop code into doing this and the above?

#    pass
        
# From effbot.org/zone/yenc-decoder.htm -- does not suffer from yDecodeOLD's bug -pjenvey
yenc42 = string.join(map(lambda x: chr((x-42) & 255), range(256)), '')
yenc64 = string.join(map(lambda x: chr((x-64) & 255), range(256)), '')
def yDecode(data):
    #file = StringIO(data)
    buffer = []
    #while 1:
    #    line = file.readline()
    for line in data:
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
    return ''.join(buffer)
                                 
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

def UUDecode(data):
    # Decode it
    #file = StringIO(data)
    buffer = []

    #while 1:
    for line in data:
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

    return ''.join(buffer)

def assembleNZBFile(nzbFile):
    """ Assemble the final file from all the NZBFile's decoded segments """
    # FIXME: don't overwrite existing files
    #info('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
    #info('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
    #info('file: ' + nzbFile.fileNameGuess)
    #info('$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$')
    file = open(nzbFile.getDestination(), 'wb')
    for nzbSegment in nzbFile.nzbSegments:

        # FIXME: do i need binary mode to read?
        # FIXME: trying this with binary off throws an exception in the print line
        # below. it does seem like the reading of the segment file is not workign right
        decodedSegmentFile = open(nzbSegment.getDestination(), 'rb')
        info('asseml : ' + nzbSegment.getDestination())
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
    for nzbf in nzb.nzbFileElements:
        if not nzbf.isAllSegmentsDecoded():
            done = False
            break

    if done:
        Hellanzb.nzbfileDone.acquire()
        Hellanzb.nzbfileDone.notify()
        Hellanzb.nzbfileDone.release()
