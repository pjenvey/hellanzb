"""
troll - verify/repair/unarchive/decompress files downloaded with nzbget

TODO
o More work on passwords. Ideally troll should be able to determine some common rar
archive passwords on it's own
o the decompressor isn't thread safe. we'll have to convert this to a Decompressor class
to prevent this. Ziplink should be able to spawn a troll thread on it's own, while it goes
back to monitoring the queue

@author pjenvey
"""
import Hellanzb, os, popen2, re
from distutils import spawn
from threading import Thread, Condition
from Util import *

__id__ = '$Id$'

def init():
    """ initialization """
    global UNRAR_CMD
    debug('Troll Init')
    
    # doppelganger
    for exe in [ 'rar', 'unrar' ]:
        if spawn.find_executable(exe):
            UNRAR_CMD = exe

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

    def __init__(self):
        self.file = DecompressionThread.musicFiles[0]
        DecompressionThread.musicFiles.remove(self.file)

        self.type = getMusicType(self.file)

        Thread.__init__(self)
        
    def run(self):
        """ decompress the song, then remove ourself from the active thread pool """
        # Catch exceptions here just in case, to ensure notify() will finally be called
        try:
            decompressMusicFile(self.file, self.type)
        except Exception, e:
            error('There was an unexpected problem while decompressing the musc file: ' + \
                  os.path.basename(self.file) + ': ' + str(e.__class__) + ': ' + str(e))

        # Decrement the thread count AND immediately notify the caller
        DecompressionThread.cv.acquire()
        DecompressionThread.pool.remove(self)
        DecompressionThread.cv.notify()
        DecompressionThread.cv.release()
    
    def start(self):
        """ add ourself to the active pool """
        DecompressionThread.pool.append(self)

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
    p = popen2.Popen4('file -b "' + absPath + '"')
    output = p.fromchild.readlines()
    p.fromchild.close()
    verifyReturnCode = os.WEXITSTATUS(p.wait())

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

def decompressMusicFiles(dirName):
    """ Assume the integrity of the files in the specified directory have been
verified. Iterate through the music files, and decompres them when appropriate in multiple
threads """

    # Determine the music files to decompress
    DecompressionThread.musicFiles = []
    for file in os.listdir(dirName):
        absPath = dirName + os.sep + file
        if os.path.isfile(absPath) and getMusicType(file) and getMusicType(file).shouldDecompress():
            DecompressionThread.musicFiles.append(absPath)

    if len(DecompressionThread.musicFiles) == 0:
        return
            
    info('Decompressing ' + str(len(DecompressionThread.musicFiles)) + ' files via ' +
         str(Hellanzb.MAX_DECOMPRESSION_THREADS) + ' threads..')

    # Maintain a pool of threads of the specified size until we've exhausted the
    # musicFiles list
    DecompressionThread.pool = []
    DecompressionThread.cv = Condition()
    while len(DecompressionThread.musicFiles) > 0:

        # Block the pool until we're done spawning
        DecompressionThread.cv.acquire()
        
        if len(DecompressionThread.pool) < Hellanzb.MAX_DECOMPRESSION_THREADS:
            decompressor = DecompressionThread() # will pop the next music file off the
                                                 # list
            decompressor.start()

        else:
            # Unblock and wait until we're notified of a thread's completition before
            # doing anything else
            DecompressionThread.cv.wait()
            
        DecompressionThread.cv.release()

    info('Finished Decompressing')

def decompressMusicFile(fileName, musicType):
    """ Decompress the specified file according to it's musicType """
    cmd = musicType.decompressor.replace('<FILE>', '"' + fileName + '"')

    extLen = len(getFileExtension(fileName))
    destFileName = fileName[:-extLen] + musicType.decompressToType
    
    info('Decompressing music file: ' + os.path.basename(fileName) \
         + ' to file: ' + os.path.basename(destFileName))
    cmd = cmd.replace('<DESTFILE>', '"' + destFileName+ '"')
        
    p = popen2.Popen4(cmd)
    output = p.fromchild.readlines()
    p.fromchild.close()
    returnCode = os.WEXITSTATUS(p.wait())

    if returnCode == 0:
        # Successful, move the old file away
        os.rename(fileName, os.path.dirname(fileName) + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep +
                  os.path.basename(fileName))
    
    elif returnCode > 0:
        pass
        # FIXME - propagate this to parent
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
    listCmd = UNRAR_CMD + ' l -y ' + ' "' + firstRar + '"'
    p = popen2.Popen4(listCmd)
    output = p.fromchild.readlines()
    p.fromchild.close()

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
        growlNotify('Archive Error', 'hellanzb Archive requires password:', archiveNameFromDirName(dirName),
                    True)
        raise FatalError('Cannot continue, this archive requires a RAR password and there is none set')

    if isPassworded:
        cmd = UNRAR_CMD + ' x -y -p' + rarPassword + ' "' + firstRar + '"'
    else:
        cmd = UNRAR_CMD + ' x -y ' + ' "' + firstRar + '"'
    
    info('Unraring..')
    p = popen2.Popen4(cmd)
    output = p.fromchild.readlines()
    p.fromchild.close()
    verifyReturnCode = os.WEXITSTATUS(p.wait())

    os.chdir(oldWd)

    if verifyReturnCode > 0:
        errMsg = 'There was a problem during unrar, output:\n\n'
        for line in output:
            errMsg += line
        raise FatalError(errMsg)
    
    info('Finished unraring')
    processComplete(dirName, 'rar',
                    lambda file : os.path.isfile(file) and isRar(file) and not isAlbumCoverArchive(file))

def processPars(dirName):
    """ Verify the integrity of the files in the specified directory via par2. If files need
repair and there are enough recovery blocks, repair the files. If files need repair and
there are not enough recovery blocks, raise a fatal exception """
    # Just incase we're running the program again, and we already successfully processed
    # the pars, don't bother doing it again
    if os.path.isfile(dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + '.par_done'):
        info('Skipping par processing')
        return
    
    info('Verifying via pars..')

    dirName = dirName + os.sep
    verifyCmd = 'par2 v "' + dirName + '*.PAR2" "' + dirName + '*.par2"' + ' *_broken'
    repairCmd = 'par2 r "' + dirName + '*.PAR2" "' + dirName + '*.par2"' + ' *_broken' 

    p = popen2.Popen4(verifyCmd)
    output = p.fromchild.readlines()
    p.fromchild.close()
    verifyReturnCode = os.WEXITSTATUS(p.wait())
        
    if verifyReturnCode == 0:
        # Verified
        info('Par verification passed')

    elif verifyReturnCode == 1:
        # Repair required and possible
        info('Repairing files via par..')
        
        p = popen2.Popen4(repairCmd)
        output = p.fromchild.readlines()
        p.fromchild.close()
        repairReturnCode = os.WEXITSTATUS(p.wait())

        if repairReturnCode == 0:
            # Repaired
            info('Par repair successfully completed')
        elif repairReturnCode > 0:
            # We should never get here. If verifyReturnCode is 1, we're guaranteed a
            # successful repair
            raise FatalError('Unable to par repair: an unexpected problem has occurred')
            
    elif verifyReturnCode > 1:
        # Repair required and impossible

        # First, if the repair is not possible, double check the output for what files are
        # missing or damaged (a missing file is considered as damaged in this case). they
        # may be unimportant
        damagedAndRequired, neededBlocks = parseParNeedsBlocksOutput(output)

        # The archive is only totally broken when we're missing required files
        if len(damagedAndRequired) > 0:
            growlNotify('Error', 'hellanzb Cannot par repair:', archiveNameFromDirName(dirName) +
                        '\nNeed ' + neededBlocks + ' more recovery blocks', True)
            raise FatalError('Unable to par repair: there are not enough recovery blocks, need: ' +
                             neededBlocks + 'more')

    processComplete(dirName, 'par', isPar)

def parseParNeedsBlocksOutput(output):
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
            else:
                file = damagedRE.sub('', line)

            if isRequiredFile(file):
                error('Archive missing required file: ' + file)
                damagedAndRequired.append(file)
            else:
                warn('Archive missing non-required file: ' + file)

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
    for file in filter(moveFileFilterFunction, [dirName + os.sep + file for file in os.listdir(dirName)]):
        os.rename(file, os.path.dirname(file) + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep +
                  os.path.basename(file))

    # And make a note of the completition
    # NOTE: we've just moved the files out of dirName, and we usually do a dirHas check
    # before calling the process function. but this is more explicit, and could be used to
    # show the overall status on the webapp
    touch(dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + '.' + processStateName + '_done')
    
def trollmain(dirName):
    """ main, mayn """
    
    # exit the program if we lack required binaries
    assertIsExe('par2')

    # Put files we've processed and no longer need (like pars rars) in this dir
    processedDir = dirName + os.sep + Hellanzb.PROCESSED_SUBDIR
    
    if not os.path.exists(dirName) or not os.path.isdir(dirName):
        raise FatalError('Directory does not exist: ' + dirName)
                          
    if not os.path.exists(processedDir):
        os.mkdir(processedDir)
    elif not os.path.isdir(processedDir):
        raise FatalError('Unable to create processed directory, a non directory already exists there')

    # First, find broken files, in prep for repair. Grab the msg id and nzb
    # file names while we're at it
    msgId = None
    nzbFile = None
    brokenFiles = []
    files = os.listdir(dirName)
    for file in files:
        absoluteFile = dirName + os.sep + file
        if os.path.isfile(absoluteFile):
            if stringEndsWith(file, '_broken'):
                # Keep track of the broken files
                brokenFiles.append(absoluteFile)
                
            elif file[0:len('.msgid_')] == '.msgid_':
                msgId = file[len('.msgid_'):]

            elif getFileExtension(file).lower() == 'nzb':
                nzbFile = file

    # If there are required broken files and we lack pars, punt
    if len(brokenFiles) > 0 and containsRequiredFiles(brokenFiles) and not dirHasPars(dirName):
        errorMessage = 'Unable to process directory: ' + dirName + '\n' + ' '*4 + \
            'This directory has the following broken files: '
        for brokenFile in brokenFiles:
            errorMessage += '\n' + ' '*8 + brokenFile
            errorMessage += '\n    and contains no par2 files for repair'
        raise FatalError(errorMessage)

    if dirHasPars(dirName):
        processPars(dirName)

    # grab the rar password if one exists
    if dirHasRars(dirName):
        rarPassword = None
        if os.path.isdir(Hellanzb.PASSWORDS_DIR):
                         
            for file in os.listdir(Hellanzb.PASSWORDS_DIR):
                if file == msgId:

                    absPath = Hellanzb.PASSWORDS_DIR + os.sep + msgId
                    if not os.access(absPath, os.R_OK):
                        raise FatalError('Refusing to continue: unable to read rar password (no read access)')
                
                msgIdFile = open(absPath)
                rarPassword = msgIdFile.read().rstrip()
        
        processRars(dirName, rarPassword)
    
    if dirHasMusicFiles(dirName):
        decompressMusicFiles(dirName)

    # Move other cruft out of the way
    deleteDuplicates(dirName)
    if os.path.isfile(dirName + os.sep + nzbFile) and os.access(dirName + os.sep + nzbFile, os.R_OK):
        os.rename(dirName + os.sep + nzbFile, dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + nzbFile)

    # We're done
    info("Finished processing: " + archiveNameFromDirName(dirName))
    growlNotify('Archive Success', 'hellanzb Done Processing:', archiveNameFromDirName(dirName),
                True)

def troll(dirName,archiveName):
    try:
        trollmain(dirName)
    except FatalError, fe:
        cleanUp(dirName)
        error('An unexpected problem occurred for archive: ' +
              archiveName + ', problem: ' + fe.message)
    except Exception, e:
        cleanUp(dirName)
        error('An unexpected problem occurred for archive: ' +
              archiveName + ': ' + str(e.__class__) + ': ' + str(e))


def archiveNameFromDirName(dirName):
    """ Extract the name of the archive from the archive's absolute path """
    # pop off separator and basename
    while dirName[len(dirName) - 1] == os.sep:
        dirName = dirName[0:len(dirName) - 1]
    return os.path.basename(dirName)
