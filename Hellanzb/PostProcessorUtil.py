"""
PostProcessorUtil - support functions for the PostProcessor

@author pjenvey
"""
import Hellanzb, os, re
from threading import Thread
from Logging import *
from Util import *

__id__ = '$Id$'

# FIXME: this class should be a KnownFileType class, or something. file types other than
# music might want to be decompressed
class MusicType:
    """ Defines a music file type, and whether or not this program should attempt to
decompress the music (to wav, generally) if it comes across this type of file """
    extension = None
    decompressor = None
    decompressToType = None
    musicTypes = [] # class var -- supported MusicTypes

    def __init__(self, extension, decompressor, decompressToType):
        self.extension = extension

        if decompressor != None and decompressor != "":
            # exit if we lack the required decompressor
            assertIsExe(decompressor)
            self.decompressor = decompressor

        self.decompressToType = decompressToType

    def shouldDecompress(self):
        if self.decompressor == None:
            return False
        return True

class DecompressionThread(Thread):
    """ decompress a file in a separate thread """

    def __init__(self, parent):
        self.file = DecompressionThread.musicFiles[0]
        DecompressionThread.musicFiles.remove(self.file)

        self.type = getMusicType(self.file)
        
        self.parent = parent

        Thread.__init__(self)
        
    def run(self):
        """ decompress the song, then remove ourself from the active thread pool """
        # Catch exceptions here just in case, to ensure notify() will finally be called
        archive = archiveName(os.path.dirname(self.file))
        try:
            decompressMusicFile(self.file, self.type)
        except Exception, e:
            error(archive + ': There was an unexpected problem while decompressing the musc file: ' + \
                  os.path.basename(self.file), e)

        # Decrement the thread count AND immediately notify the caller
        self.parent.removeDecompressor(self)
    
    def start(self):
        """ add ourself to the active pool """
        self.parent.addDecompressor(self)

        Thread.start(self)

def dirHasRars(dirName):
    """ Determine if the specified directory contains rar files """
    for file in os.listdir(dirName):
        if isRar(dirName + os.sep + file):
            return True
    return False

def dirHasPars(dirName):
    """ Determine if the specified directory contains par files """
    return dirHasFileType(dirName, 'par2')

def dirHasMusicFiles(dirName):
    """ Determine if the specified directory contains any known music files """
    return dirHasFileTypes(dirName, getMusicTypeExtensions())

def isRar(fileName):
    """ Determine if the specified file is a rar """
    absPath = fileName
    fileName = os.path.basename(fileName)

    ext = getFileExtension(fileName)
    if ext and ext.lower() == 'rar':
        return True

    # If it doesn't end in rar, use unix file(1) 
    p = Ptyopen('file -b "' + absPath + '"')
    output, status = p.readlinesAndWait()
    returnCode = os.WEXITSTATUS(status)

    if len(output) > 0:
        line = output[0]
        if len(line) > 2 and line[0:3].lower() == 'rar':
            return True

    # NOTE We could check for part001 or ending in 001, r01 or something similar if we
    # don't want to use file(1)
    return False

def isPar(fileName):
    """ Determine if the specified file is a par """
    fileName = os.path.basename(fileName)
    ext = getFileExtension(fileName)
    if ext and ext.lower() == 'par2':
        return True
    return False

def isAlbumCoverArchive(fileName):
    """ determine if the archive (zip or rar) file likely contains album cover art, which
requires special handling """
    # FIXME: check for images jpg/gif/tiff, and or look for key words like 'cover',
    # 'front' 'back' in the file name, AND within the archive

    # NOTE: i notice rar has this option:
    #i[i|c|h|t]=<string>
    #        Find string in archives.
    #Supports following optional parameters:
    # i - case insensitive search (default);
    # c - case sensitive search;
    
    #return True
    return False

def isRequiredFile(fileName):
    """ Given the specified of file name, determine if the file is required for the full
completition of the unarchiving process (ie, the completition of this
program). Non-Required files are those such as .NFOs, .SFVs, etc. Other types of files are
considered important (such as .RARs, .WAVs, etc). If any required files are missing or
broken, PAR2 files will be required to repair """
    isRequired = True
    for ext in Hellanzb.NOT_REQUIRED_FILE_TYPES:
        if getFileExtension(fileName) == ext:
            isRequired = False

    return isRequired

def containsRequiredFiles(fileList):
    """ Given the list of file names, determine if any of the files are required for the full
completition of the unarchiving process (ie, the completition of this
program). Non-Required files are those such as .NFOs, .SFVs, etc. Other types of files are
considered important (such as .RARs, .WAVs, etc). If any required files are missing or
broken, PAR2 files will be required to repair """
    for file in fileList:
        if isRequiredFile(file):
            return True
    return False

def defineMusicType(extension, decompressor, decompressToType):
    """ Create a new instance of a MusicType and add it to the list of known music types """
    MusicType.musicTypes.append(MusicType(extension, decompressor, decompressToType))

def deleteDuplicates(dirName):
    for file in os.listdir(dirName):
        if stringEndsWith(file, '_duplicate') and os.access(file, os.W_OK):
            os.remove(file)

def cleanUp(dirName):
    """ Tidy up after a FatalError """
    if not os.path.exists(dirName) or not os.path.isdir(dirName):
        return

    # Delete the processed dir only if it doesn't contain anything
    try:
        os.rmdir(dirName + os.sep + Hellanzb.PROCESSED_SUBDIR)
    except OSError:
        pass

def getMusicTypeExtensions():
    """ Return a list of the file name extensions for all known MusicType instances """
    musicTypeExtensions = []
    for musicType in MusicType.musicTypes:
            musicTypeExtensions.append(musicType.extension)
    return musicTypeExtensions

def getMusicType(fileName):
    """ Determine the specified file's MusicType instance """
    ext = getFileExtension(fileName)
    for musicType in MusicType.musicTypes:
        if ext == musicType.extension:
            return musicType
    return False

def decompressMusicFile(fileName, musicType):
    """ Decompress the specified file according to it's musicType """
    cmd = musicType.decompressor.replace('<FILE>', '"' + fileName + '"')

    extLen = len(getFileExtension(fileName))
    destFileName = fileName[:-extLen] + musicType.decompressToType

    archive = archiveName(os.path.dirname(fileName))
    
    info(archive + ': Decompressing to ' + str(musicType.decompressToType) + ': ' + \
         os.path.basename(fileName))
    cmd = cmd.replace('<DESTFILE>', '"' + destFileName + '"')

    # user defined cmds might spit out to stderr
    p = Ptyopen(cmd, capturestderr = True)
    # Ignore stderr
    p.childerr.close()
    output, status = p.readlinesAndWait()
    returnCode = os.WEXITSTATUS(status)

    if returnCode == 0:
        # Successful, move the old file away
        os.rename(fileName, os.path.dirname(fileName) + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep +
                  os.path.basename(fileName))
    
    elif returnCode > 0:
        # FIXME: not getting stderr here
        msg = 'There was a problem while decompressing music file: ' + os.path.basename(fileName) + \
            ' output:\n'
        for line in output:
            msg = msg + line
        error(msg)

        # FIXME - could propagate this to parent
        # see threading.thread.interrupt_main()
        #raise FatalError("Unable to decompress music file: " + fileName)

def processRars(dirName, rarPassword):
    """ If the specified directory contains rars, unrar them. """
    # sort the filenames and assume the first thing to look like a rar is what we want to
    # begin unraring with
    firstRar = None
    files = os.listdir(dirName)
    files.sort()
    for file in files:
        absPath = dirName + os.sep + file
        if os.path.isfile(absPath) and isRar(absPath) and not isAlbumCoverArchive(absPath):
            firstRar = file
            break

    if firstRar == None:
        # FIXME: this last part is dumb, when isAlbumCoverArchive works, this FetalError
        # could mean the only rars we found are were album covers
        raise FatalError('Unable to locate the first rar')

    # run rar from dirName, so it'll output files there
    oldWd = os.getcwd()
    os.chdir(dirName)

    # First, list the contents of the rar, if any filenames are preceeded with *, the rar
    # is passworded
    listCmd = Hellanzb.UNRAR_CMD + ' l -y ' + ' "' + firstRar + '"'
    p = Ptyopen(listCmd)
    output, listStatus = p.readlinesAndWait()
    listReturnCode = os.WEXITSTATUS(listStatus)

    isPassworded = False
    withinFiles = False
    for line in output:
        line = line.rstrip()

        if withinFiles:
            if line[0:1] == ' ':
                # not passworded
                continue

            elif line[0:1] == '*':
                # passworded
                isPassworded = True

            elif len(line) >= 79 and line[0:80] == '-'*79:
                # done with the file listing
                break

        # haven't found the file listing yet
        elif len(line) >= 79 and line[0:80] == '-'*79:
            withinFiles = True

    if isPassworded and rarPassword == None:
        growlNotify('Archive Error', 'hellanzb Archive requires password:', archiveName(dirName),
                    True)
        raise FatalError('Cannot continue, this archive requires a RAR password and there is none set')

    if isPassworded:
        cmd = Hellanzb.UNRAR_CMD + ' x -y -p' + rarPassword + ' "' + firstRar + '"'
    else:
        cmd = Hellanzb.UNRAR_CMD + ' x -y ' + ' "' + firstRar + '"'
    
    info(archiveName(dirName) + ': Unraring..')
    p = Ptyopen(cmd)
    output, status = p.readlinesAndWait()
    unrarReturnCode = os.WEXITSTATUS(status)

    os.chdir(oldWd)

    if unrarReturnCode > 0:
        errMsg = 'There was a problem during unrar, output:\n\n'
        for line in output:
            errMsg += line
        raise FatalError(errMsg)
    
    info(archiveName(dirName) + ': Finished unraring')
    processComplete(dirName, 'rar',
                    lambda file : os.path.isfile(file) and isRar(file) and not isAlbumCoverArchive(file))

def processPars(dirName):
    """ Verify the integrity of the files in the specified directory via par2. If files need
repair and there are enough recovery blocks, repair the files. If files need repair and
there are not enough recovery blocks, raise a fatal exception """
    # Just incase we're running the program again, and we already successfully processed
    # the pars, don't bother doing it again
    if os.path.isfile(dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + '.par_done'):
        info(archiveName(dirName) + ': Skipping par processing')
        return
    
    info(archiveName(dirName) + ': Verifying via pars..')

    dirName = dirName + os.sep
    verifyCmd = 'par2 v "' + dirName + '*.PAR2" "' + dirName + '*.par2" "' + dirName + '*_broken"'
    repairCmd = 'par2 r "' + dirName + '*.PAR2" "' + dirName + '*.par2" "' + dirName + '*_broken"'

    p = Ptyopen(verifyCmd)
    output, verifyStatus = p.readlinesAndWait()
    verifyReturnCode = os.WEXITSTATUS(verifyStatus)
        
    if verifyReturnCode == 0:
        # Verified
        info(archiveName(dirName) + ': Par verification passed')

    elif verifyReturnCode == 1:
        # Repair required and possible
        info(archiveName(dirName) + ': Repairing files via par..')
        
        p = Ptyopen(repairCmd)
        output, repairStatus = p.readlinesAndWait()
        repairReturnCode = os.WEXITSTATUS(repairStatus)

        if repairReturnCode == 0:
            # Repaired
            info(archiveName(dirName) + ': Par repair successfully completed')
        elif repairReturnCode > 0:
            # We should never get here. If verifyReturnCode is 1, we're guaranteed a
            # successful repair
            raise FatalError('Unable to par repair: an unexpected problem has occurred')
            
    elif verifyReturnCode > 1:
        # Repair required and impossible

        # First, if the repair is not possible, double check the output for what files are
        # missing or damaged (a missing file is considered as damaged in this case). they
        # may be unimportant
        damagedAndRequired, neededBlocks = parseParNeedsBlocksOutput(archiveName(dirName), output)

        # The archive is only totally broken when we're missing required files
        if len(damagedAndRequired) > 0:
            growlNotify('Error', 'hellanzb Cannot par repair:', archiveName(dirName) +
                        '\nNeed ' + neededBlocks + ' more recovery blocks', True)
            raise FatalError('Unable to par repair: archive requires ' + neededBlocks + \
                             ' more recovery blocks for repair')

    processComplete(dirName, 'par', isPar)

def parseParNeedsBlocksOutput(archive, output):
    """ Return a list of broken or damaged required files from par2 v output, and the required
blocks needed. Will also log warn the user when it finds either of these kinds of files,
or log error when they're required """
    damagedAndRequired = []
    neededBlocks = None
    damagedRE = re.compile(r'"\ -\ damaged\.\ Found\ \d+\ of\ \d+\ data\ blocks\.')

    for line in output:
        line = line.rstrip()
            
        index = line.find('Target:')
        if index > -1 and stringEndsWith(line, 'missing.') or damagedRE.search(line):
            # Strip any preceeding curses junk
            line = line[index:]

            # Finally, get just the filename
            line = line[len('Target: "'):]

            if stringEndsWith(line, 'missing.'):
                file = line[:-len('" - missing.')]
                # FIXME: putting msgids in the log output would help you read it
                # better. Could queue up these messages for later processing (return them
                # in this function)
                errMsg = archive + ': Archive missing required file: ' + file
                warnMsg = archive + ': Archive missing non-required file: ' + file
            else:
                file = damagedRE.sub('', line)
                errMsg = archive + ': Archive has damaged, required file: ' + file
                warnMsg = archive + ': Archive has damaged, non-required file: ' + file

            if isRequiredFile(file):
                error(errMsg)
                damagedAndRequired.append(file)
            else:
                warn(warnMsg)

        elif line[0:len('You need ')] == 'You need ' and \
            stringEndsWith(line, ' more recovery blocks to be able to repair.'):
            line = line[len('You need '):]
            neededBlocks = line[:-len(' more recovery blocks to be able to repair.')]
            
    return damagedAndRequired, neededBlocks
        
def processComplete(dirName, processStateName, moveFileFilterFunction):
    """ Once we've finished a particular processing state, this function will be called to
move the files we processed out of the way, and touch a file on the filesystem indicating
this state is done """
    # ensure we pass the absolute path to the filter function
    if moveFileFilterFunction != None:
        for file in filter(moveFileFilterFunction, [dirName + os.sep + file for file in os.listdir(dirName)]):
            os.rename(file, os.path.dirname(file) + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + \
                      os.path.basename(file))

    # And make a note of the completition
    # NOTE: we've just moved the files out of dirName, and we usually do a dirHas check
    # before calling the process function. but this is more explicit, and could be used to
    # show the overall status on the webapp
    touch(dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + '.' + processStateName + '_done')

def getRarPassword(msgId):
    """ Get the specific rar password set for the specified msgId """
    if os.path.isdir(Hellanzb.PASSWORDS_DIR):
                     
        for file in os.listdir(Hellanzb.PASSWORDS_DIR):
            if file == msgId:

                absPath = Hellanzb.PASSWORDS_DIR + os.sep + msgId
                if not os.access(absPath, os.R_OK):
                    raise FatalError('Refusing to continue: unable to read rar password (no read access)')
            
            msgIdFile = open(absPath)
            return msgIdFile.read().rstrip()

