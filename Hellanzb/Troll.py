"""
troll - verify/repair/unarchive/decompress files downloaded with nzbget

TODO
o support passing in a password to the unrarer
o better signal handling (especially re the threads -- they ignore ctrl-c)
  # module-thread.html says:
  # Caveats:
  # Threads interact strangely with interrupts: the KeyboardInterrupt exception will be
  # received by an arbitrary thread. (When the signal module is available, interrupts
  # always go to the main thread.)

@author pjenvey
"""
import os, popen2, string, sys, time
from distutils import spawn
from StringIO import StringIO
from threading import Thread, Condition

__id__ = "$Id"

debugMode = False 

def init():
    """ initialization """
    global UNRAR_CMD, brokenFiles # FIXME
    debug("Troll Init")
    
    # doppelganger
    if spawn.find_executable("rar"):
        UNRAR_CMD = "rar"
    elif spawn.find_executable("unrar"):
        UNRAR_CMD = "unrar"

    # global vars that users shouldn't modify
    brokenFiles = [] # list of broken files (their renamed names)


# FIXME: this class should be a KnownFileType class, or something. file types other than
# music might want to be decompressed
class MusicType:
    """ Defines a music file type, and whether or not this program should attempt to
decompress the music (to wav, generally) if it comes across this type of file """
    extension = None
    decompressor = None
    musicTypes = [] # class var -- supported MusicTypes

    def __init__(self, extension, decompressor):
        self.extension = extension

        if decompressor != None and decompressor != "":
            # exit if we lack the required decompressor
            assertIsExe(decompressor)
            self.decompressor = decompressor

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
        except:
            error("There was an unexpected problem while decompressing the musc file: " + \
                  os.path.basename(self.file))

        # Decrement the thread count AND immediately notify the caller
        DecompressionThread.cv.acquire()
        DecompressionThread.pool.remove(self)
        DecompressionThread.cv.notify()
        DecompressionThread.cv.release()
    
    def start(self):
        """ add ourself to the active pool """
        DecompressionThread.pool.append(self)

        Thread.start(self)

class FatalError(Exception):
    """ An error that will cause the program to exit """
    def __init__(self, message):
        self.message = message

def warn(message):
    """ Log a message at the warning level """
    sys.stderr.write("Warning: " + message + "\n")

def error(message):
    """ Log a message at the error level """
    sys.stderr.write("Error: " + message + "\n")

def info(message):
    """ Log a message at the info level """
    print message

def debug(message):
    if debugMode:
        print message

def assertIsExe(exe):
    """ Abort the program if the specified file is not in our PATH and executable """
    if len(exe) > 0:
        exe = exe.split()[0]
        if spawn.find_executable(exe) == None or os.access(exe, os.X_OK):
            raise FatalError("Cannot continue program, required executable not in path: " + exe)

def dirHasRars(dirName):
    """ Determine if the specified directory contains rar files """
    for file in os.listdir(dirName):
        if isRar(file):
            return True
    return False

def dirHasPars(dirName):
    """ Determine if the specified directory contains par files """
    return dirHasFileTypes(dirName, [ "par2", "PAR2" ])

def dirHasMusicFiles(dirName):
    """ Determine if the specified directory contains any known music files """
    return dirHasFileTypes(dirName, getMusicTypeExtensions())

def dirHasFileType(dirName, getFileExtension):
    return dirHasFileTypes(dirName, [ getFileExtension ])
    
def dirHasFileTypes(dirName, getFileExtensionList):
    """ Determine if the specified directory contains any files of the specified type -- that
type being defined by it's filename extension """
    for file in os.listdir(dirName):
        for type in getFileExtensionList:
            if (getFileExtension(file)) == type:
                return True
    return False

def isRar(fileName):
    """ Determine if the specified file is a rar """
    fileName = os.path.basename(fileName)

    if getFileExtension(fileName) == "rar":
        return True
    # FIXME either ends in .rar or has part001 or something. could also use unix file() but wont
    # support windows

    # if none, look for something containing a 001 at the end. ??
    
    # typical formats:
    # blah.part01.rar
    return False

def isPar(fileName):
    """ Determine if the specified file is a par """
    fileName = os.path.basename(fileName)
    ext = getFileExtension(fileName)
    if ext == "par2" or ext == "PAR2":
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
    for ext in NOT_REQUIRED_FILE_TYPES:
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

def defineMusicType(extension, decompressor):
    """ Create a new instance of a MusicType and add it to the list of known music types """
    MusicType.musicTypes.append(MusicType(extension, decompressor))

def deleteDuplicates(dirName):
    for file in os.listdir(dirName):
        if stringEndsWith(file, "_duplicate") and os.access(file, os.W_OK):
            os.remove(file)

def cleanUp(dirName):
    """ Tidy up after a FatalError """
    if not os.path.exists(dirName) or not os.path.isdir(dirName):
        return

    # If we had a fatal error and we moved the _broken files, put them back as to not
    # confuse anyone about what's in the directory
    for file in brokenFiles:
        fixedName = file[:-len("_broken")]
        os.rename(fixedName, file)

    # Deleted the processed dir only if it doesn't contain anything
    try:
        os.rmdir(dirName + os.sep + "processed")
    except OSError:
        pass

def getMusicTypeExtensions():
    """ Return a list of the file name extensions for all known MusicType instances """
    musicTypeExtensions = []
    for musicType in MusicType.musicTypes:
            musicTypeExtensions.append(musicType.extension)
    return musicTypeExtensions

def renameBrokenFile(fileName):
    """ Handle renaming broken files, so that their may be an attempt to repair them. Add the
renamed file name to the specified list """
    fixedName = fileName[:-len("_broken")]
    
    if os.path.isfile(fixedName):
        raise FatalError("Unable to rename broken file: " + fileName + ", the file: " + fixedName + \
    " already exists")
    
    warn("Renamed broken file: " + fileName + " to " + fixedName)
    os.rename(fileName, fixedName)

def getFileExtension(fileName):
    """ Return the extenion of the specified file name """
    if len(fileName) > 2 and fileName.find(".") > -1:
        return string.lower(os.path.splitext(fileName)[1][1:])

def stringEndsWith(string, match):
    matchLen = len(match)
    if len(string) >= matchLen and string[-matchLen:] == match:
        return True
    return False

def getMusicType(fileName):
    """ Determine the specified file's MusicType instance """
    ext = getFileExtension(fileName)
    for musicType in MusicType.musicTypes:
        if ext == musicType.extension:
            return musicType
    return False

def touch(fileName):
    """ Set the access/modified times of this file to the current time. Create the file if it
does not exist. """
    fd = os.open(fileName, os.O_WRONLY | os.O_CREAT, 0666)
    os.close(fd)
    os.utime(fileName, None)

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

    # Maintain a pool of threads of the specified size until we've exhausted the
    # musicFiles list
    DecompressionThread.pool = []
    DecompressionThread.cv = Condition()
    while len(DecompressionThread.musicFiles) > 0:

        # Block the pool until we're done spawning
        DecompressionThread.cv.acquire()
        
        if len(DecompressionThread.pool) < MAX_DECOMPRESSION_THREADS:
            decompressor = DecompressionThread() # will pop the next music file off the
                                                 # list
            decompressor.start()

        else:
            # Unblock and wait until we're notified of a thread's completition before
            # doing anything else
            DecompressionThread.cv.wait()
            
        DecompressionThread.cv.release()
        

def decompressMusicFile(fileName, musicType):
    """ Decompress the specified file according to it's musicType """
    cmd = musicType.decompressor.replace("<FILE>", "\"" + fileName + "\"")

    extLen = len(getFileExtension(fileName))
    destFileName = fileName[:-extLen] + "wav"
    
    info("Decompressing music file: " + os.path.basename(fileName) \
        + " to file: " + os.path.basename(destFileName))
    cmd = cmd.replace("<DESTFILE>", "\"" + destFileName+ "\"")

    p = popen2.Popen4(cmd)
    output = p.fromchild.readlines()
    p.fromchild.close()
    returnCode = os.WEXITSTATUS(p.wait())

    # Let's not be too specific. All we care about is whether or not the decompress
    # succeeded
    if returnCode > 0:
        pass
        # FIXME - propagate this to parent
        # see threading.thread.interrupt_main()
        #raise FatalError("Unable to decompress music file: " + fileName)
        
    return False

def processRars(dirName, rarPassword):
    """ If the specified directory contains rars, unrar them. """

    if not dirHasRars(dirName):
        return
    
    # sort the filenames and assume the first thing to look like a rar is what we want to
    # begin unraring with
    firstRar = None
    files = os.listdir(dirName)
    files.sort()
    for file in files:
        if os.path.isfile(dirName + os.sep + file) and isRar(file) and not isAlbumCoverArchive(file):
            firstRar = file
            break

    if firstRar == None:
        raise FatalError("Unable to locate the first rar")

    # run rar from dirName, so it'll output files there
    oldWd = os.getcwd()
    os.chdir(dirName)

    # First, list the contents of the rar, if any filenames are preceeded with *, the rar
    # is passworded
    listCmd = UNRAR_CMD + " l -y " + " \"" + firstRar + "\""
    p = popen2.Popen4(listCmd)
    output = p.fromchild.readlines()
    p.fromchild.close()

    isPassworded = False
    withinFiles = False
    for line in output:
        line = line.rstrip()

        if withinFiles:
            if line[0:1] == " ":
                # not passworded
                continue

            elif line[0:1] == "*":
                # passworded
                isPassworded = True

            elif len(line) >= 79 and line[0:80] == "-"*79:
                # done with the file listing
                break

        # haven't found the file listing yet
        elif len(line) >= 79 and line[0:80] == "-"*79:
            withinFiles = True

    if isPassworded and rarPassword == None:
        raise FatalError("Cannot continue, this archive requires a RAR password")

    if isPassworded:
        cmd = UNRAR_CMD + " x -y -p" + rarPassword + " \"" + firstRar + "\""
    else:
        cmd = UNRAR_CMD + " x -y " + " \"" + firstRar + "\""
    
    info("Unraring..")
    p = popen2.Popen4(cmd)
    output = p.fromchild.readlines()
    p.fromchild.close()
    verifyReturnCode = os.WEXITSTATUS(p.wait())

    os.chdir(oldWd)

    if verifyReturnCode > 0:
        errMsg = "There was a problem during unrar, output:\n\n"
        for line in output:
            errMsg += line
        raise FatalError(errMsg)

    processComplete(dirName, "rar",
                    lambda file : os.path.isfile(file) and isRar(file) and not isAlbumCoverArchive(file))

def processPars(dirName):
    """ Verify the integrity of the files in the specified directory via par2. If files need
repair and there are enough recovery blocks, repair the files. If files need repair and
there are not enough recovery blocks, raise a fatal exception """
    # Just incase we're running the program again, and we already successfully processed
    # the pars, don't bother doing it again
    if os.path.isfile(dirName + os.sep + PROCESSED_SUBDIR + os.sep + ".par_done"):
        info("Skipping par processing")
        return
    
    info("Verifying via pars..")

    dirName = dirName + os.sep
    verifyCmd = "par2 v \"" + dirName + "*.PAR2\" \"" + dirName + "*.par2\""
    repairCmd = "par2 r \"" + dirName + "*.PAR2\" \"" + dirName + "*.par2\""

    p = popen2.Popen4(verifyCmd)
    output = p.fromchild.readlines()
    p.fromchild.close()
    verifyReturnCode = os.WEXITSTATUS(p.wait())

    # First, if the repair is not possible, double check the output for what files are
    # missing. they may be unimportant
    if verifyReturnCode > 1:
        missingAndRequired = []

        for line in output:
            line = line.rstrip()
            index = line.find("Target:")
            if index > -1 and stringEndsWith(line, "missing."):
                # Strip any preceeding curses junk
                line = line[index:]

                # Finally, get just the filename
                line = line[len("Target: \""):]
                file = line[:-len("\" - missing.")]

                if isRequiredFile(file):
                    error("Archive missing required file: " + file)
                    missingAndRequired.append(file)
                else:
                    warn("Archive missing non-required file: " + file)

        # If we didn't find any missing files that are required, act as if the archive was
        # verified
        if len(missingAndRequired) == 0:
            verifyReturnCode = 0
        
    if verifyReturnCode == 0:
        # Verified
        info("Par verification passed")
    elif verifyReturnCode == 1:
        # Repair required and possible
        info("Repairing files via par..")
        
        p = popen2.Popen4(repairCmd)
        output = p.fromchild.readlines()
        p.fromchild.close()
        repairReturnCode = os.WEXITSTATUS(pipe.wait())

        if repairReturnCode == 0:
            # Repaired
            info("Par repair successfully completed")
        elif repairReturnCode > 0:
            # We should never get here. If verifyReturnCode is 1, we're guaranteed a
            # successful repair
            raise FatalError("Unable to par repair: an unexpected problem has occurred")
            
    elif verifyReturnCode > 1:
        # Repair required and impossible
        # TODO: statistics about how many blocks are needed would be nice
        raise FatalError("Unable to par repair: there are not enough recovery blocks")

    processComplete(dirName, "par", isPar)
        
def processComplete(dirName, processStateName, moveFileFilterFunction):
    """ Once we've finished a particular processing state, this function will be called to
move the files we processed out of the way, and touch a file on the filesystem indicating
this state is done """

    for file in filter(moveFileFilterFunction, os.listdir(dirName)):
        if not debugMode:
            os.rename(dirName + os.sep + file, dirName + os.sep + PROCESSED_SUBDIR + os.sep + file)

    # And make a note of the completition
    # NOTE: we've just moved the files out of dirName, and we usually do a dirHas check
    # before calling the process function. but this is more explicit, and could be used to
    # show the overall status on the webapp
    if not debugMode:
        touch(dirName + os.sep + PROCESSED_SUBDIR + os.sep + "." + processStateName + "_done")
    
def troll(dirName):
    """ main, mayn """
    global brokenFiles # FIXME gross
    
    # exit the program if we lack required binaries
    assertIsExe("par2")

    # Put files we've processed and no longer need (like pars rars) in this dir
    processedDir = dirName + os.sep + PROCESSED_SUBDIR
    
    if not os.path.exists(dirName) or not os.path.isdir(dirName):
        raise FatalError("Directory does not exist: " + dirName)
                          
    if not os.path.exists(processedDir):
        os.mkdir(processedDir)
    elif not os.path.isdir(processedDir):
        raise FatalError("Unable to create processed directory, a non directory already exists there")

    
    # First, find and rename broken files, in prep for repair
    files = os.listdir(dirName)
    for file in files:
        absoluteFile = dirName + os.sep + file
        
        if os.path.isfile(absoluteFile):
    
            if stringEndsWith(file, "_broken"):
                # Keep track of the broken files
                brokenFiles.append(absoluteFile)
                renameBrokenFile(absoluteFile)

    # If there are required broken files and we lack pars, punt
    if len(brokenFiles) > 0 and containsRequiredFiles(brokenFiles):
    
        if not dirHasPars(dirName):
            errorMessage = "Unable to process directory: " + dirName + "\n" + " "*4 + \
                "This directory has the following broken files: "
            for brokenFile in brokenFiles:
                errorMessage += "\n" + " "*8 + brokenFile
                errorMessage += "\n    and contains no par2 files for repair"
            raise FatalError(errorMessage)

    
    if dirHasPars(dirName):
        processPars(dirName)

    # If we've made it this far, we've simply verified the integrity of the existing
    # directory, or fixed all the broken files and no longer need to worry about them
    brokenFiles = []

    # grab the rar password if one exists
    # FIXME:
    rarPassword = None
        
    # Continue the unarchive process
    processRars(dirName, rarPassword)
    
    if dirHasMusicFiles(dirName):
        decompressMusicFiles(dirName)

    deleteDuplicates(dirName)
