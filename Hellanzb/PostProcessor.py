"""
PostProcessor (aka troll) - verify/repair/unarchive/decompress files downloaded with
nzbget

TODO
o More work on passwords. Ideally troll should be able to determine some common rar
archive passwords on it's own

@author pjenvey
"""
import Hellanzb, os
from threading import Thread, Condition, Lock
from Logging import *
from PostProcessorUtil import *
from Util import *

__id__ = '$Id$'

class PostProcessor(Thread):
    """ A post processor (formerly troll) instance runs in it's own thread """
    dirName = None
    decompressionThreadPool = None
    decompressorCondition = None
    background = None
    
    msgId = None
    nzbFile = None
    
    def start(self):
        """ Maintain a list of active PostProcessors """
        Hellanzb.postProcessorLock.acquire()
        # FIXME: could block if there are too many processors going
        Hellanzb.postProcessors.append(self)
        Hellanzb.postProcessorLock.release()
        
        Thread.start(self)

    def __init__(self, dirName, background = True):
        """ Ensure sanity of this instance before starting """
        # abort if we lack required binaries
        assertIsExe('par2')
        
        self.dirName = dirName
        
        # Whether or not this thread is the only thing happening in the app (-p mode)
        self.background = background
        
        self.decompressionThreadPool = []

        # NOTE/FIXME: was considering a Lock instead of RLock here. but even though the
        # function calls are in this object, they're being called by the decompressor
        # threads, so RLock is fine
        self.decompressorCondition = Condition()

        Thread.__init__(self)

    def addDecompressor(self, decompressorThread):
        """ Add a decompressor thread to the pool and notify the caller """
        self.decompressorCondition.acquire()
        self.decompressionThreadPool.append(decompressorThread)
        self.decompressorCondition.notify()
        self.decompressorCondition.release()

    def removeDecompressor(self, decompressorThread):
        """ Remove a decompressor thread from the pool and notify the caller """
        self.decompressorCondition.acquire()
        self.decompressionThreadPool.remove(decompressorThread)
        self.decompressorCondition.notify()
        self.decompressorCondition.release()

    def stop(self):
        """ Perform any cleanup and remove ourself from the pool before exiting """
        cleanUp(self.dirName)

        Hellanzb.postProcessorLock.acquire()
        Hellanzb.postProcessors.remove(self)
        Hellanzb.postProcessorLock.release()
    
    def run(self):
        """ do the work """
        try:
            self.postProcess()
            
        except FatalError, fe:
            self.stop()
            error('A problem occurred for archive: ' + archiveName(self.dirName), fe)
            if not self.background:
                raise
        
        except Exception, e:
            self.stop()
            error('An unexpected problem occurred for archive: ' + archiveName(self.dirName), e)
            if not self.background:
                raise
    
    def decompressMusicFiles(self):
        """ Assume the integrity of the files in the specified directory have been
    verified. Iterate through the music files, and decompres them when appropriate in multiple
    threads """
        # Determine the music files to decompress
        DecompressionThread.musicFiles = []
        for file in os.listdir(self.dirName):
            absPath = self.dirName + os.sep + file
            if os.path.isfile(absPath) and getMusicType(file) and getMusicType(file).shouldDecompress():
                DecompressionThread.musicFiles.append(absPath)
    
        if len(DecompressionThread.musicFiles) == 0:
            return
                
        info('Decompressing ' + str(len(DecompressionThread.musicFiles)) + ' files via ' +
             str(Hellanzb.MAX_DECOMPRESSION_THREADS) + ' threads..')
    
        # Maintain a pool of threads of the specified size until we've exhausted the
        # musicFiles list
        while len(DecompressionThread.musicFiles) > 0:
    
            # Block the pool until we're done spawning
            self.decompressorCondition.acquire()
            
            if len(self.decompressionThreadPool) < Hellanzb.MAX_DECOMPRESSION_THREADS:
                decompressor = DecompressionThread(parent = self) # will pop the next
                                                                  # music file off the
                                                                  # list
                decompressor.start()
    
            else:
                # Unblock and wait until we're notified of a thread's completition before
                # doing anything else
                self.decompressorCondition.wait()
                
            self.decompressorCondition.release()
    
        info('Finished Decompressing')

    def finishedPostProcess(self):
        """ finish the post processing work """
        # Move other cruft out of the way
        deleteDuplicates(self.dirName)
        
        if self.nzbFile != None:
            if os.path.isfile(self.dirName + os.sep + self.nzbFile) and \
                    os.access(self.dirName + os.sep + self.nzbFile, os.R_OK):
                os.rename(self.dirName + os.sep + self.nzbFile,
                          self.dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + self.nzbFile)

        # Move out anything else that is tagged as not required
        for file in os.listdir(self.dirName):
            ext = getFileExtension(file)
            if len(ext) > 0 and ext in Hellanzb.NOT_REQUIRED_FILE_TYPES:
                os.rename(self.dirName + os.sep + file,
                          self.dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + file)
    
        # We're done
        info("Finished processing: " + archiveName(self.dirName))
        growlNotify('Archive Success', 'hellanzb Done Processing:', archiveName(self.dirName),
                    True)

    def postProcess(self):
        """ process the specified directory """
        # Check for shutting down flag before doing any significant work
        checkShutdown()
        
        # Put files we've processed and no longer need (like pars rars) in this dir
        processedDir = self.dirName + os.sep + Hellanzb.PROCESSED_SUBDIR
        
        if not os.path.exists(self.dirName) or not os.path.isdir(self.dirName):
            raise FatalError('Directory does not exist: ' + self.dirName)
                              
        if not os.path.exists(processedDir):
            os.mkdir(processedDir)
        elif not os.path.isdir(processedDir):
            raise FatalError('Unable to create processed directory, a non directory already exists there')
    
        # First, find broken files, in prep for repair. Grab the msg id and nzb
        # file names while we're at it
        brokenFiles = []
        files = os.listdir(self.dirName)
        for file in files:
            absoluteFile = self.dirName + os.sep + file
            if os.path.isfile(absoluteFile):
                print 'file: ' + file
                if stringEndsWith(file, '_broken'):
                    # Keep track of the broken files
                    brokenFiles.append(absoluteFile)
                    
                elif len(file) > 7 and file[0:len('.msgid_')] == '.msgid_':
                    self.msgId = file[len('.msgid_'):]
    
                elif len(file) > 3 and file.find('.') > -1 and getFileExtension(file).lower() == 'nzb':
                    self.nzbFile = file
    
        # If there are required broken files and we lack pars, punt
        if len(brokenFiles) > 0 and containsRequiredFiles(brokenFiles) and not dirHasPars(self.dirName):
            errorMessage = 'Unable to process directory: ' + self.dirName + '\n' + ' '*4 + \
                'This directory has the following broken files: '
            for brokenFile in brokenFiles:
                errorMessage += '\n' + ' '*8 + brokenFile
                errorMessage += '\n    and contains no par2 files for repair'
            raise FatalError(errorMessage)

        if dirHasPars(self.dirName):
            checkShutdown()
            processPars(self.dirName)
        
        if dirHasRars(self.dirName):
            # grab the rar password if one exists
            rarPassword = getRarPassword(self.msgId)
            
            checkShutdown()
            processRars(self.dirName, rarPassword)
        
        if dirHasMusicFiles(self.dirName):
            checkShutdown()
            decompressMusicFiles(self.dirName)

        self.finishedPostProcess()
