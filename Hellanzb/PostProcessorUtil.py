"""

PostProcessorUtil - support functions for the PostProcessor

(c) Copyright 2005 Philip Jenvey, Ben Bangert
[See end of file]
"""
import os, re, sys, time, Hellanzb
from shutil import move
from threading import Thread
from time import time
from Hellanzb.Log import *
from Hellanzb.Util import *

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

        if decompressor != None and decompressor != '':
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

    def __init__(self, parent, dirName):
        self.file = parent.musicFiles[0]
        parent.musicFiles.remove(self.file)

        self.dirName = dirName

        self.type = getMusicType(self.file)
        
        self.parent = parent

        Thread.__init__(self)

    def failure(self):
        """ There was a problem decompressing -- let the parent know """
        self.parent.failedLock.acquire()
        self.parent.failedToProcesses.append(self.file)
        self.parent.failedLock.release()
            
    def run(self):
        """ decompress the song, then remove ourself from the active thread pool """
        # Catch exceptions here just in case, to ensure notify() will finally be called
        archive = archiveName(self.dirName)
        try:
            decompressMusicFile(self.file, self.type, archive)

        except SystemExit, se:
            # Shutdown, stop what we're doing
            self.parent.removeDecompressor(self)
            return

        except FatalError, fe:
            error(archive, fe)
            self.failure()
            
        except Exception, e:
            error(archive + ': There was an unexpected problem while decompressing the music file: ' + \
                  os.path.basename(self.file), e)
            self.failure()

        # Decrement the thread count AND immediately notify the caller
        self.parent.removeDecompressor(self)
    
    def start(self):
        """ add ourself to the active pool """
        self.parent.addDecompressor(self)

        Thread.start(self)

class DirName(str):
    """ A hack to print out the correct dirName via Util.archiveName, when processing nested
    sub directories"""
    def __init__(self, *args, **kwargs):
        self.parentDir = None
        str.__init__(self, *args, **kwargs)

    def isSubDir(self):
        return self.parentDir != None

class ParExpectsUnsplitFiles(Exception):
    """ Before Par2ing, the post processor finds any files that look like they need to be
    assembled (E.g. file.avi.001, file.avi.002)

    Now, before continuing, I'll just make it clear that, IMHO (pjenvey), posters using
    .001-.XXX files (with some exceptions) like this should be tapped on the shoulder and
    asked nicely to please use rar for splitting up files instead

    Now, here's where it gets tricky. Posters who use .001-.XXX files AND use par2 files,
    seem to typically create their par2 files to expect the .001-.XXX files. That makes
    sense, your par files should validate the files you downloaded without having to do
    any work on them first

    Other posters, who IMHO, should be beaten severly over the head with a blunt obtuse
    angled object, create their par2 files to expect the ASSEMBLED version of .001-.XXX
    files (for file.avi.001-.XXX, it expects file.avi). So these knuckleheads expect you
    to combine the split up file parts, then run par2. Fine, hellanzb will handle them too

    So when the files-to-be-assembled are determined, they are passed along to
    PostProcessor's par2 code. If par2 command line determines it's missing files that we
    identified earlier as needing to assembled, this exception is thrown, letting us know
    we need to do the assembly work and then re-run the par2 code again

    Otherwise we simply do the assembly afterwards
    """
    pass

def dirHasRars(dirName):
    """ Determine if the specified directory contains rar files """
    for file in os.listdir(dirName):
        if isRar(dirName + os.sep + file):
            return True
    return False

def dirHasPars(dirName):
    """ Determine if the specified directory contains par files """
    for file in os.listdir(dirName):
        file = dirName + os.sep + file
        if isPar(file):
            return True
    return False

def dirHasMusic(dirName):
    """ Determine if the specified directory contains any known music files """
    return dirHasFileTypes(dirName, getMusicTypeExtensions())

RAR_HEADER = 'Rar!'
def isRar(fileName):
    """ Determine if the specified file is a rar """
    if not os.path.isfile(fileName):
        return False
    
    ext = getFileExtension(fileName)
    if ext and ext.lower() == 'rar':
        return True

    fh = open(fileName)
    firstFourBytes = fh.read(4)
    fh.close()

    if firstFourBytes == RAR_HEADER:
        return True

    # NOTE: We should probably check for part001 or ending in 001, r01 etc. Otherwise we
    # could possibly miss damaged rar files that are named this way
    return False

def isPar(fileName):
    """ Determine if the specified file is a par2 or par1 file """
    return isPar2(fileName) or isPar1(fileName)

def isPar2(fileName):
    """ Determine if the specified file is a par2 file """
    ext = getFileExtension(fileName)
    if not ext:
        return False
    
    # FIXME: the downloader doesn't make _broken files (nzbget did) -- but it might in the
    # future
    ext = ext.lower()
    if ext == 'par2' or ext == 'par2_broken':
        return True

    return False

par1ParityVolumeFileExtRe = re.compile(r'[pq]\d{2}$')
EOLbroken = re.compile(r'_broken$')
def isPar1(fileName):
    """ Determine if the specified file is a par1 file """
    ext = getFileExtension(fileName)
    if not ext:
        return False

    ext = ext.lower()
    if ext == 'par' or ext == 'par_broken':
        return True
    if par1ParityVolumeFileExtRe.match(EOLbroken.sub('', ext)):
        return True

    return False

def isDuplicate(fileName):
    """ Determine if the specified file is a duplicate """
    if stringEndsWith(fileName, '_duplicate') or re.match(r'.*_duplicate\d{0,4}', fileName):
        return True
    return False

def isRequiredFile(fileName):
    """ Given the specified of file name, determine if the file is required for the full
    completition of the unarchiving process (ie, the completition of this
    program). Non-Required files are those such as .NFOs, .SFVs, etc. Other types of files
    are considered important (such as .RARs, .WAVs, etc). If any required files are
    missing or broken, PAR2 files will be required to repair """
    isRequired = True
    ext = getFileExtension(fileName)
    if ext != None and ext.lower() in Hellanzb.NOT_REQUIRED_FILE_TYPES:
        isRequired = False

    return isRequired

def containsRequiredFiles(fileList):
    """ Given the list of file names, determine if any of the files are required for the
    full completition of the unarchiving process (ie, the completition of this
    program). Non-Required files are those such as .NFOs, .SFVs, etc. Other types of files
    are considered important (such as .RARs, .WAVs, etc). If any required files are
    missing or broken, PAR2 files will be required to repair """
    for file in fileList:
        if isRequiredFile(file):
            return True
    return False

def defineMusicType(extension, decompressor, decompressToType):
    """ Create a new instance of a MusicType and add it to the list of known music types """
    try:
        MusicType.musicTypes.append(MusicType(extension, decompressor, decompressToType))
    except FatalError:
        error('Problem in config file with defineMusicType() for extension: ' + str(extension))
        raise

def deleteDuplicates(dirName):
    """ Delete _duplicate files """
    for file in os.listdir(dirName):
        if isDuplicate(file) and os.access(file, os.W_OK):
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

def decompressMusicFile(fileName, musicType, archive = None):
    """ Decompress the specified file according to its musicType """
    cmd = musicType.decompressor.replace('<FILE>', '"' + fileName + '"')

    extLen = len(getFileExtension(fileName))
    destFileName = fileName[:-extLen] + musicType.decompressToType

    if archive == None:
        archive = archiveName(os.path.dirname(fileName))
    
    info(archive + ': Decompressing to ' + str(musicType.decompressToType) + ': ' + \
         os.path.basename(fileName))
    cmd = cmd.replace('<DESTFILE>', '"' + destFileName + '"')

    t = Topen(cmd)
    output, returnCode = t.readlinesAndWait()

    if returnCode == 0:
        # Successful, move the old file away
        move(fileName, os.path.dirname(fileName) + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep +
             os.path.basename(fileName))
        
    elif returnCode > 0:
        msg = 'There was a problem while decompressing music file: ' + os.path.basename(fileName) + \
            ' output:\n'
        for line in output:
            msg += line
        msg = msg.strip()
        raise FatalError(msg)

def dotRarFirstCmp(x, y):
    """ Sort .rars first """
    if stringEndsWith(x.lower(), '.rar') and \
        stringEndsWith(y.lower(), '.rar'):
        return cmp(x, y)
    
    if stringEndsWith(x.lower(), '.rar'):
        return -1
        
    if stringEndsWith(y.lower(), '.rar'):
        return 1

    return cmp(x, y)
        
def processRars(dirName, rarPassword):
    """ If the specified directory contains rars, unrar them. """
    if not isFreshState(dirName, 'rar'):
        return

    # loop through a sorted list of the files until we find the first
    # rar, then unrar it. skip over any files we know unrar() has
    # already processed, and repeat
    processedRars = []
    files = os.listdir(dirName)
    files.sort(dotRarFirstCmp) # .rars come first
    start = time.time()
    unrared = 0
    for file in files:
        absPath = os.path.normpath(dirName + os.sep + file)
        
        if absPath not in processedRars and not os.path.isdir(absPath) and \
                isRar(absPath) and not isDuplicate(absPath) and \
                not stringEndsWith(absPath, '.1') and not stringEndsWith(absPath, '_broken'):
            # Found the first rar. this is always the first rar to start extracting with,
            # unless there is a .rar file. However, rar seems to be smart enough to look
            # for a .rar file if we specify this incorrect first file anyway
            
            justProcessedRars = unrar(dirName, file, rarPassword)
            processedRars.extend(justProcessedRars)

            # Move the processed rars out of the way immediately
            for rar in justProcessedRars:
                moveToProcessed(rar)
                
            unrared += 1

    e = time.time() - start
    rarTxt = 'rar'
    if unrared > 1:
        rarTxt += 's'
    info(archiveName(dirName) + ': Finished unraring (%i %s, took: %.1fs)' % (unrared,
                                                                              rarTxt, e))
    processComplete(dirName, 'rar',
                    lambda file : os.path.isfile(file) and isRar(file))

"""
## From unrarsrc-3.4.3

// rar return codes

enum { SUCCESS,WARNING,FATAL_ERROR,CRC_ERROR,LOCK_ERROR,WRITE_ERROR,
       OPEN_ERROR,USER_ERROR,MEMORY_ERROR,CREATE_ERROR,USER_BREAK=255};
"""
def unrar(dirName, fileName, rarPassword = None, pathToExtract = None):
    """ Unrar the specified file. Returns all the rar files we extracted from """
    fileName = os.path.normpath(dirName + os.sep + fileName)

    # By default extract to the file's dir
    if pathToExtract == None:
        pathToExtract = dirName

    # First, list the contents of the rar, if any filenames are preceeded with *, the rar
    # is passworded
    if rarPassword != None:
        # Specify the password during the listing, in the case that the data AND headers
        # are passworded
        listCmd = Hellanzb.UNRAR_CMD + ' l -y "-p' + rarPassword + '" "' + fileName + '"'
    else:
        listCmd = Hellanzb.UNRAR_CMD + ' l -y -p-' + ' "' + fileName + '"'
    t = Topen(listCmd)
    output, listReturnCode = t.readlinesAndWait()

    if rarPassword == None and listReturnCode == 3:
        # For CRC_ERROR (password failed) example:
        # Encrypted file:  CRC failed in h.rar (password incorrect ?)
        # FIXME: only sticky this growl if we're a background processor
        growlNotify('Archive Error', 'hellanzb requires password', archiveName(dirName) + \
                    ' requires a rar password for extraction', True)
        raise FatalError('Cannot continue, this archive requires a RAR password. Run ' + sys.argv[0] + \
                         ' -p on the archive directory with the -P option to specify a password')
        
    elif listReturnCode > 0:
        errMsg = 'There was a problem during the rar listing, output:\n'
        for line in output:
            errMsg += line
        errMsg = errMsg.strip()
        raise FatalError(errMsg)

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
        # FIXME: only sticky this growl if we're a background processor
        growlNotify('Archive Error', 'hellanzb requires password', archiveName(dirName) + \
                    ' requires a rar password for extraction', True)
        raise FatalError('Cannot continue, this archive requires a RAR password. Run ' + sys.argv[0] + \
                         ' -p on the archive directory with the -P option to specify a password')

    if isPassworded:
        cmd = Hellanzb.UNRAR_CMD + ' x -y "-p' + rarPassword + '" "' + fileName + '" "' + \
            pathToExtract + '"'
    else:
        cmd = Hellanzb.UNRAR_CMD + ' x -y -p-' + ' "' + fileName + '" "' + pathToExtract + '"'
    
    info(archiveName(dirName) + ': Unraring ' + os.path.basename(fileName) + '..')
    t = Topen(cmd)
    output, unrarReturnCode = t.readlinesAndWait()

    if unrarReturnCode > 0:
        errMsg = 'There was a problem during unrar, output:\n\n'
        err = ''
        for line in output:
            err += line
        errMsg += err.strip()
        raise FatalError(errMsg)

    # Return a tally of all the rars extracted from
    processedRars = []
    prefix = 'Extracting from '
    for line in output:
        if len(line) > len(prefix) + 1 and line.find(prefix) == 0:
            rarFile = line[len(prefix):].rstrip()
            # Distrust the dirname rar returns (just incase)
            rarFile = os.path.normpath(os.path.dirname(fileName) + os.sep + os.path.basename(rarFile))
            
            if rarFile not in processedRars:
                processedRars.append(rarFile)

    return processedRars

def findPar2Groups(dirName):
    """ Find all par2 file groupings """
    pars = [file for file in os.listdir(dirName) if isPar(file)]
    pars.sort()

    # A map of a wildcards defining a par file group and its par file names. The wildcard
    # isn't actually used as a wildcard, it's simply a label
    parGroups = {}
    parGroupOrder = [] # maintain the correct order
    for file in pars:
        if isPar2(file):
            key = flattenPar2Name(file)
        else:
            key = flattenPar1Name(file)

        if parGroups.has_key(key):
            group = parGroups[key]
        else:
            group = []
            parGroups[key] = group
            parGroupOrder.append(key)

        group.append(file)

    return parGroups, parGroupOrder

par2RecoveryPacketRe = re.compile(r'.vol\d+[-+]\d+.')
def flattenPar2Name(file):
    """ Flatten a PAR2 filename for grouping (remove the unique characters distinguishing it
    from other par files in its same group) via wildcards (and add wildcard values where
    appropriate)

    A list of par2 files containing multiple groups might look like:
    
    download.part1.par2            download.part2.par2
    download.part1.vol000+01.PAR2  download.part2.vol000+01.PAR2
    download.part1.vol001+02.PAR2  download.part2.vol001+02.PAR2
    download.part1.vol003+04.PAR2  download.part2.vol003+04.PAR2

    Would have 2 wildcards: download.part1*.{par2,PAR2}
                            download.part2*.{par2,PAR2}
                            
    or possibly even:
    
    dataGroupA.vol007+08.PAR2  dataGroupA.vol053+48.PAR2 dataGroupB.vol28+25.PAR2
    dataGroupA.vol015+13.PAR2  dataGroupB.vol07+08.PAR2  dataGroupC.vol12+10.PAR2
    dataGroupA.vol028+25.PAR2  dataGroupB.vol15+13.PAR2  dataGroupC.vol22+19.PAR2

    Would have 3 wildcards: dataGroupA*.{par2,PAR2}
                            dataGroupB*.{par2,PAR2}
                            dataGroupC*.{par2,PAR2}

    From the PAR2 Specification: http://www.par2.net/par2spec.php (Note the specification
    specifies '-' as the vol delimiter, however Usenet appears to use '+' for some unknown
    reason)

    PAR 2.0 files should always end in ".par2". For example, "file.par2". If a file
    contains recovery slices, the ".par2" should be preceded by ".volXX-YY" where XX to YY
    is the range of exponents for the recovery slices. For example,
    "file.vol20-29.par2". More than 2 digits should be used if necessary. Any exponents
    that contain fewer digits than the largest exponent should be preceded by zeros so
    that all filenames have the same length. For example,
    "file.vol075-149.par2". Exponents should start at 0 and go upwards.

    If multiple PAR files are generated, they may either have a constant number of slices
    per file (e.g. 20, 20, 20, ...) or exponentially increasing number of slices (e.g., 1,
    2, 4, 8, ...). Note that to store 1023 slices takes 52 files if each has 20 slices,
    but takes only 10 files with the exponential pattern.

    When generating multiple PAR files, it is expected that one file be generated without
    any slices and containing all main, file description, and input file checksum
    packets. The other files should also include the main, file description and input file
    checksum packets. This repeats data that cannot be recovered.
    
    """
    # Removing all the '.vol' cruft reveals the group
    file = par2RecoveryPacketRe.sub('.', file)
    return file[:-5] + '*.{par2,PAR2}'

def flattenPar1Name(file):
    """ Flatten a PAR1 filename for grouping (remove the unique characters distinguishing it
    from other par files in its same group) via wildcards (and add wildcard values where
    appropriate)
    
    A typical par1 listing:
    
    Data.part01.PAR  Data.part01.P01
    Data.part01.P02

    Would have a wildcard of: Data.part01.*
    
    From http://www.par2.net/parspec.php:
    A parity volume set consists of two parts. First there is a .PAR file (the index
    file).

    Second there are the parity volume files. They are named .P00, .P01,
    P02..... PXX. (After .P99, there will be .Q00...)
    """
    # Removing the file extension reveals the group
    return file[:-len(getFileExtension(file))] + '*'

def processPars(dirName, needAssembly = None):
    """ Verify (and repair) the integrity of the files in the specified directory via par2
    (which supports both par1 and par2 files). If files need repair and there are not
    enough recovery blocks, raise a fatal exception. Each different grouping of pars will
    have their own explicit par2 process ran on the grouping's files """
    # Just incase we're running the program again, and we already successfully processed
    # the pars, don't bother doing it again
    if not isFreshState(dirName, 'par'):
        info(archiveName(dirName) + ': Skipping par processing')
        return

    start = time.time()
    dirName = DirName(dirName + os.sep)

    # Remove any .1 files after succesful par2 that weren't previously there (aren't in
    # this list)
    dotOneFiles = [file for file in os.listdir(dirName) if file[-2:] == '.1']

    parGroups, parGroupOrder = findPar2Groups(dirName)
    for wildcard in parGroupOrder:
        parFiles = parGroups[wildcard]
        
        par2(dirName, parFiles, wildcard, needAssembly)
        
        # Successful par2, move them out of the way
        for parFile in parFiles:
            moveToProcessed(dirName + parFile)

    e = time.time() - start
    parTxt = 'par group'
    groupCount = len(parGroups)
    if groupCount > 1:
        parTxt += 's'
    info(archiveName(dirName) + ': Finished par verifiy (%i %s, took: %.1fs)' % (groupCount,
                                                                              parTxt, e))
    
    processComplete(dirName, 'par', lambda file : isPar(file) or \
                    (file[-2:] == '.1' and file not in dotOneFiles))

"""
## From par2cmdline-0.4

// Return type of par2cmdline
typedef enum Result
{
  eSuccess                     = 0,

  eRepairPossible              = 1,  // Data files are damaged and there is
                                     // enough recovery data available to
                                     // repair them.

  eRepairNotPossible           = 2,  // Data files are damaged and there is
                                     // insufficient recovery data available
                                     // to be able to repair them.

  eInvalidCommandLineArguments = 3,  // There was something wrong with the
                                     // command line arguments

  eInsufficientCriticalData    = 4,  // The PAR2 files did not contain sufficient
                                     // information about the data files to be able
                                     // to verify them.

  eRepairFailed                = 5,  // Repair completed but the data files
                                     // still appear to be damaged.


  eFileIOError                 = 6,  // An error occured when accessing files
  eLogicError                  = 7,  // In internal error occurred
  eMemoryError                 = 8,  // Out of memory

} Result;
"""
def par2(dirName, parFiles, wildcard, needAssembly = None):
    """ Verify (and repair) the integrity of the files in the specified directory via par2. If
    files need repair and there are not enough recovery blocks, raise a fatal exception """
    info(archiveName(dirName) + ': Verifying via par group: ' + wildcard + '..')
    if needAssembly == None:
        needAssembly = {}
        
    repairCmd = 'par2 r'
    for parFile in parFiles:
        repairCmd += ' "' + dirName + parFile + '"'
        
    t = Topen(repairCmd)
    output, returnCode = t.readlinesAndWait()

    if returnCode == 0:
        # FIXME: checkout for 'repaired blah' messages.
        # for line in output:
        #     if line.find(''):
        #         parRepaired = True
        #
        # if parRepaired:
        #     info(archiveName(dirName) + ': Par repair successfully completed')
        # else:
        
        # Verified
        return

    elif returnCode == 2:
        # Repair required and impossible

        # First, if the repair is not possible, double check the output for what files are
        # missing or damaged (a missing file is considered as damaged in this case). they
        # may be unimportant
        damagedAndRequired, allMissing, neededBlocks, isPar1Archive = \
            parseParNeedsBlocksOutput(archiveName(dirName), output)

        for file in allMissing:
            if needAssembly.has_key(file):
                # Found a file we need to assemble for Par2. Throw us back out to handle
                # that work, we'll run par2 again later
                raise ParExpectsUnsplitFiles('')

        # The archive is only totally broken when we're missing required files
        if len(damagedAndRequired) > 0:
            needType = 'blocks'
            if isPar1Archive:
                needType = 'files (par1)'
                
            growlNotify('Error', 'hellanzb Cannot par repair:', archiveName(dirName) + \
                        '\nNeed ' + neededBlocks + ' more recovery ' + needType, True)
            # FIXME: download more pars and try again
            raise FatalError('Unable to par repair: archive requires ' + neededBlocks + \
                             ' more recovery ' + needType + ' for repair')
            # otherwise processComplete here (failed)

    else:
        # Abnormal behavior -- let the user deal with it
        raise FatalError('par2 repair failed: returned code: ' + str(returnCode) + \
                         '. Please run par2 manually for more information, par2 cmd: ' + \
                         repairCmd)

def parseParNeedsBlocksOutput(archive, output):
    """ Return a list of broken or damaged required files from par2 v output, and the
    required blocks needed. Will also log warn the user when it finds either of these
    kinds of files, or log error when they're required """
    damagedAndRequired = []
    allMissing = []
    neededBlocks = None
    damagedRE = re.compile(r'"\ -\ damaged\.\ Found\ \d+\ of\ \d+\ data\ blocks\.')
    isPar1Archive = False

    maxSpam = 4 # only spam this many lines (before truncating)
    spammed = 0
    extraSpam = []
    for line in output:
        line = line.rstrip()
            
        index = line.find('Target:')
        if index > -1 and stringEndsWith(line, 'missing.') or damagedRE.search(line):
            # Strip any preceeding curses junk
            line = line[index:]

            # Extract the filename
            line = line[len('Target: "'):]

            if stringEndsWith(line, 'missing.'):
                file = line[:-len('" - missing.')]
                # FIXME: Could queue up these messages for later processing (return them
                # in this function)
                errMsg = archive + ': Archive missing required file: ' + file
                warnMsg = archive + ': Archive missing non-required file: ' + file
                allMissing.append(file)
            else:
                file = damagedRE.sub('', line)
                errMsg = archive + ': Archive has damaged, required file: ' + file
                warnMsg = archive + ': Archive has damaged, non-required file: ' + file

            if isRequiredFile(file):
                if spammed <= maxSpam:
                    error(errMsg)
                    spammed += 1
                else:
                    extraSpam.append(errMsg)
                    
                damagedAndRequired.append(file)
            else:
                if spammed <= maxSpam:
                    warn(warnMsg)
                    spammed += 1
                else:
                    extraSpam.append(errMsg)

        elif line[0:len('You need ')] == 'You need ' and \
            stringEndsWith(line, ' to be able to repair.'):
            line = line[len('You need '):]
            
            if line.find(' more recovery files ') > -1:
                # Par 1 format
                isPar1Archive = True
                neededBlocks = line[:-len(' more recovery files to be able to repair.')]
            else:
                # Par 2
                neededBlocks = line[:-len(' more recovery blocks to be able to repair.')]

    if spammed > maxSpam and len(extraSpam):
        error(' <hellanzb truncated the missing/damaged listing, see the log for full output>')
        
        # Hi I'm lame. Why do I even bother enforcing warn() usage anyway
        lastMsg = extraSpam[-1]
        if lastMsg.find('non-required') > 1:
            warn(lastMsg)
        else:
            error(lastMsg)
            
    return damagedAndRequired, allMissing, neededBlocks, isPar1Archive

SPLIT_RE = re.compile(r'.*\.\d{3,4}$')
SPLIT_TS_RE = re.compile(r'.*\.\d{3,4}\.ts$', re.I)
def findSplitFiles(dirName):
    """ Find files split into chunks. This currently supports the following formats:

    Files ending with 3-4 digits, e.g.:

    ArchiveA.avi.001                ArchiveB.mpg.0001
    ArchiveA.avi.002                ArchiveB.mpg.0002
    ArchiveA.avi.003

    Files with 3-4 digits preceding the .ts extension, e.g.:

    hello.001.TS                hi.0001.ts
    hello.002.TS                hi.0002.ts
                                hi.0003.ts
    """
    toAssemble = {}

    # Find anything matching the split file re
    for file in os.listdir(dirName):
        if SPLIT_RE.match(file):
            key = file[:file.rfind('.')]
            
        elif SPLIT_TS_RE.match(file):
            noExt = file[:-3]
            key = noExt[:noExt.rfind('.')] + '.ts'
            
        else:
            continue

        if toAssemble.has_key(key):
            parts = toAssemble[key]
            parts.append(file)
        else:
            parts = []
            parts.append(file)
            toAssemble[key] = parts

    # Remove any file sets that contain rar files, just in case
    verify = toAssemble.copy()
    for key, parts in verify.iteritems():

        foundRar = False
        for part in parts:
            if isRar(dirName + os.sep + part):
                foundRar = True
                break
        if foundRar:
            toAssemble.pop(key)
            
    return toAssemble
    
def assembleSplitFiles(dirName, toAssemble):
    """ Assemble files previously found to be split in the common split formats. This could be
    a lengthy process, so this function will abort the attempt when a shutdown occurs """
    # Finally assemble the main file from the parts. Cancel the assembly and delete the
    # main file if we are CTRL-Ced
    for key, parts in toAssemble.iteritems():
        parts.sort()

        if key[-3:].lower() == '.ts':
            msg = archiveName(dirName) + ': Assembling split TS file from parts: ' + key[:-3] + '.*.ts..' 
        else:
            msg = archiveName(dirName) + ': Assembling split file from parts: ' + key + '.*..'
        info(msg)
        debug(msg + ' ' + str(parts))
        
        assembledFile = open(dirName + os.sep + key, 'w')

        for file in parts:
            partFile = open(dirName + os.sep + file)
            for line in partFile:
                assembledFile.write(line)
            partFile.close()
            
            try:
                checkShutdown()
            except SystemExit:
                # We were interrupted. Instead of waiting to finish, just delete the file. It
                # will be automatically assembled upon restart
                debug('PostProcessor: (CTRL-C) Removing unfinished file: ' + dirName + os.sep + key)
                assembledFile.close()
                try:
                    os.remove(dirName + os.sep + key)
                except:
                    pass
                raise
            
        assembledFile.close()

        for part in parts:
            moveToProcessed(dirName + os.sep + part)

def moveToProcessed(file):
    """ Move files to the processed dir """
    move(file, os.path.dirname(file) + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + \
         os.path.basename(file))
        
def processComplete(dirName, processStateName, moveFileFilterFunction):
    """ Once we've finished a particular processing state, this function will be called to
    move the files we processed out of the way, and touch a file on the filesystem
    indicating this state is done """
    # ensure we pass the absolute path to the filter function
    if moveFileFilterFunction != None:
        for file in filter(moveFileFilterFunction,
                           [dirName + os.sep + file for file in os.listdir(dirName)]):
            moveToProcessed(file)

    # And make a note of the completion
    touch(dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + '.' + processStateName + '_done')

def isFreshState(dirName, stateName):
    """ Determine if the specified state has already been completed """
    if os.path.isfile(dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + '.' + stateName + '_done'):
        return False
    return True

"""
/*
 * Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
 *                    Ben Bangert <bbangert@groovie.org>
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
