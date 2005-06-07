"""

PostProcessor (aka troll) - verify/repair/unarchive/decompress files downloaded with
nzbget

(c) Copyright 2005 Philip Jenvey, Ben Bangert
[See end of file]
"""
import Hellanzb, os, re, sys, time
from os.path import join as pathjoin
from shutil import rmtree
from threading import Thread, Condition, Lock
from Hellanzb.Log import *
from Hellanzb.PostProcessorUtil import *
from Hellanzb.Util import *

__id__ = '$Id$'

class PostProcessor(Thread):
    """ A post processor (formerly troll) instance runs in its own thread """
    dirName = None
    decompressionThreadPool = None
    decompressorCondition = None
    background = None
    musicFiles = None
    brokenFiles = None

    failedLock = None
    failedToProcesses = None
    
    msgId = None
    nzbFile = None

    def __init__(self, dirName, background = True, rarPassword = None, parentDir = None):
        """ Ensure sanity of this instance before starting """
        # abort if we lack required binaries
        assertIsExe('par2')
        
        self.dirName = os.path.realpath(dirName)
        self.dirName = DirName(self.dirName)
        
        # Whether or not this thread is the only thing happening in the app (-p mode)
        self.background = background
        
        self.decompressionThreadPool = []
        self.decompressorCondition = Condition()

        self.rarPassword = rarPassword

        # The parent directory we the originating post process call started from, if we
        # are post processing a sub directory
        self.isSubDir = False
        self.parentDir = parentDir
        if self.parentDir != None:
            self.isSubDir = True
            self.dirName.parentDir = self.parentDir
            
        self.startTime = None
    
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

        if not self.background:
            from twisted.internet import reactor
            reactor.callFromThread(reactor.stop)
    
    def run(self):
        """ do the work """
        Hellanzb.postProcessorLock.acquire()
        # FIXME: could block if there are too many processors going
        Hellanzb.postProcessors.append(self)
        Hellanzb.postProcessorLock.release()
        
        try:
            self.postProcess()
            
        except SystemExit, se:
            # sys.exit throws this. collect $200
            # FIXME: can I safely raise here instead?
            pass
        
        except FatalError, fe:
            self.stop()
            error(archiveName(self.dirName) + ': A problem occurred', fe)
            if not self.background:
                # FIXME: none of these will cause the main thread to return 1
                sys.exit(1)
                #thread.interrupt_main()
                #raise
            return
        
        except Exception, e:
            self.stop()
            error(archiveName(self.dirName) + ': An unexpected problem occurred', e)
            if not self.background:
                # not sure what happened, let's see the backtrace
                raise
            return
            
        self.stop()
    
    def processMusic(self):
        """ Assume the integrity of the files in the specified directory have been
        verified. Iterate through the music files, and decompres them when appropriate in
        multiple threads """
        if not isFreshState(self.dirName, 'music'):
            info(archiveName(self.dirName) + ': Skipping music file decompression')
            return
        
        # Determine the music files to decompress
        self.musicFiles = []
        for file in os.listdir(self.dirName):
            absPath = self.dirName + os.sep + file
            if os.path.isfile(absPath) and getMusicType(file) and getMusicType(file).shouldDecompress():
                self.musicFiles.append(absPath)
    
        if len(self.musicFiles) == 0:
            return

        self.musicFiles.sort()

        threadCount = min(len(self.musicFiles), int(Hellanzb.MAX_DECOMPRESSION_THREADS))
        
        filesTxt = 'file'
        threadsTxt = 'thread'
        if len(self.musicFiles) != 1:
            filesTxt += 's'
        if threadCount != 1:
            threadsTxt += 's'
            
        info(archiveName(self.dirName) + ': Decompressing ' + str(len(self.musicFiles)) + \
             ' ' + filesTxt + ' via ' + str(threadCount) + ' ' + threadsTxt + '..')

        # Failed decompress threads put their file names in this list
        self.failedToProcesses = []
        self.failedLock = Lock()

        # Maintain a pool of threads of the specified size until we've exhausted the
        # musicFiles list
        while len(self.musicFiles) > 0:
    
            # Block the pool until we're done spawning
            self.decompressorCondition.acquire()
            
            if len(self.decompressionThreadPool) < int(Hellanzb.MAX_DECOMPRESSION_THREADS):
                # will pop the next music file off the list
                decompressor = DecompressionThread(parent = self,         
                                                   dirName = self.dirName)
                decompressor.start()
    
            else:
                # Unblock and wait until we're notified of a thread's completition before
                # doing anything else
                self.decompressorCondition.wait()
                
            self.decompressorCondition.release()
            checkShutdown()

        # We're not finished until all the threads are done
        for decompressor in self.decompressionThreadPool:
            decompressor.join()

        if len(self.failedToProcesses) > 0:
            # Let the threads finish their logging (ScrollInterrupter can
            # lag)
            # FIXME: is this still necessary?
            time.sleep(.1)
            raise FatalError('Failed to complete music decompression')

        processComplete(self.dirName, 'music', None)
        info(archiveName(self.dirName) + ': Finished decompressing')

    def finishedPostProcess(self):
        """ finish the post processing work """
        # Move other cruft out of the way
        deleteDuplicates(self.dirName)
        
        if self.nzbFile != None:
            if os.path.isfile(self.dirName + os.sep + self.nzbFile) and \
                    os.access(self.dirName + os.sep + self.nzbFile, os.R_OK):
                os.rename(self.dirName + os.sep + self.nzbFile,
                          self.dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + self.nzbFile)

        # Move out anything else that's broken, a dupe or tagged as
        # not required
        for file in self.brokenFiles:
            if os.path.isfile(self.dirName + os.sep + file):
                os.rename(self.dirName + os.sep + file,
                          self.dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + file)

        for file in os.listdir(self.dirName):
            ext = getFileExtension(file)
            if ext != None and len(ext) > 0 and ext.lower() not in Hellanzb.KEEP_FILE_TYPES and \
                   ext.lower() in Hellanzb.NOT_REQUIRED_FILE_TYPES:
                os.rename(self.dirName + os.sep + file,
                          self.dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + file)
                
            elif re.match(r'.*_duplicate\d{0,4}', file):
                os.rename(self.dirName + os.sep + file,
                          self.dirName + os.sep + Hellanzb.PROCESSED_SUBDIR + os.sep + file)

        # Finally, nuke the processed dir. Hopefully the PostProcessor did its job and
        # there was absolutely no need for it, otherwise tough! (and disable the option
        # and try again) =]
        if hasattr(Hellanzb, 'DELETE_PROCESSED') and Hellanzb.DELETE_PROCESSED:
            msg = 'Deleting processed dir: ' + self.dirName + os.sep + \
                Hellanzb.PROCESSED_SUBDIR + \
                ', it contains: ' + str(walk(self.dirName + os.sep + \
                                             Hellanzb.PROCESSED_SUBDIR,
                                             1, return_folders = 1))
            logFile(msg)
            rmtree(self.dirName + os.sep + Hellanzb.PROCESSED_SUBDIR)
                
        # We're done
        e = time.time() - self.startTime 
        if not self.isSubDir:
            info(archiveName(self.dirName) + ': Finished processing (took: %.1fs)' % (e))
            growlNotify('Archive Success', 'hellanzb Done Processing:',
                        archiveName(self.dirName), True)
                       #self.background)
        # FIXME: could unsticky the message if we're running hellanzb.py -p
        # and preferably if the post processing took say over 30 seconds

    def postProcess(self):
        """ process the specified directory """
        # Check for shutting down flag before doing any significant work
        self.startTime = time.time()
        checkShutdown()
        
        # Put files we've processed and no longer need (like pars rars) in this dir
        processedDir = self.dirName + os.sep + Hellanzb.PROCESSED_SUBDIR
        
        if not os.path.exists(self.dirName):
            raise FatalError('Directory does not exist: ' + self.dirName)
        elif not os.path.isdir(self.dirName):
            raise FatalError('Not a directory: ' + self.dirName)
                              
        if not os.path.exists(processedDir):
            os.mkdir(processedDir)
        elif not os.path.isdir(processedDir):
            raise FatalError('Unable to create processed directory, a non directory already exists there')
    
        # First, find broken files, in prep for repair. Grab the msg id and nzb
        # file names while we're at it
        self.brokenFiles = []
        files = os.listdir(self.dirName)
        for file in files:
            absoluteFile = self.dirName + os.sep + file
            if os.path.isfile(absoluteFile):
                if stringEndsWith(file, '_broken'):
                    # Keep track of the broken files
                    self.brokenFiles.append(absoluteFile)
                    
                elif len(file) > 7 and file[0:len('.msgid_')] == '.msgid_':
                    self.msgId = file[len('.msgid_'):]
    
                elif len(file) > 3 and file.find('.') > -1 and getFileExtension(file).lower() == 'nzb':
                    self.nzbFile = file
    
        # If there are required broken files and we lack pars, punt
        if len(self.brokenFiles) > 0 and containsRequiredFiles(self.brokenFiles) and not dirHasPars(self.dirName):
            errorMessage = 'Unable to process directory: ' + self.dirName + '\n' + \
                'This directory has the following broken files: '
            for brokenFile in self.brokenFiles:
                errorMessage += '\n' + ' '*4 + brokenFile
            errorMessage += '\nand contains no par2 files for repair'
            raise FatalError(errorMessage)

        if dirHasPars(self.dirName):
            checkShutdown()
            processPars(self.dirName)
        
        if dirHasRars(self.dirName):
            checkShutdown()
            processRars(self.dirName, self.rarPassword)
        
        if dirHasMusic(self.dirName):
            checkShutdown()
            self.processMusic()

        # Post process sub directories
        for file in os.listdir(self.dirName):
            if file == Hellanzb.PROCESSED_SUBDIR:
                continue
            
            if os.path.isdir(pathjoin(self.dirName, file)):
                if not self.isSubDir:
                    troll = PostProcessor(pathjoin(self.dirName, file),
                                          parentDir = self.dirName)
                else:
                    troll = PostProcessor(pathjoin(self.dirName, file),
                                          parentDir = self.parentDir)
                troll.postProcess()

        self.finishedPostProcess()

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
