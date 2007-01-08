"""

PostProcessor (aka troll) - verify/repair/unarchive/decompress files downloaded with
nzbget

(c) Copyright 2005 Philip Jenvey, Ben Bangert
[See end of file]
"""
import gc, os, re, sys, time, Hellanzb
from os.path import join as pathjoin
from shutil import move, rmtree
from threading import Thread, Condition, Lock, RLock
from Hellanzb.Log import *
from Hellanzb.Logging import prettyException
from Hellanzb.PostProcessorUtil import *
from Hellanzb.Util import *

__id__ = '$Id$'

class PostProcessor(Thread):
    """ A post processor (formerly troll) instance runs in its own thread """

    # These attributes are routed to self.archive via __getattr__/__setattr__
    archiveAttrs = ('id', 'isParRecovery', 'rarPassword', 'deleteProcessed', 'skipUnrar',
                    'toStateXML', 'msgid')

    def __init__(self, archive, background = True, subDir = None):
        """ Ensure sanity of this instance before starting """
        # The archive to post process
        self.archive = archive
	
	# Determine the newzbin category of the archive
	self.category = archive.category
    
        # DirName is a hack printing out the correct directory name when running nested
        # post processors on sub directories
        if subDir:
            # Make a note of the parent directory the originating post process call
            # started from
            self.isSubDir = True
            self.subDir = subDir
            self.dirName = DirName(pathjoin(archive.archiveDir, self.subDir))
            self.dirName.parentDir = archive.archiveDir
            self.archiveName = archiveName(self.dirName.parentDir)
        else:
            self.isSubDir = False
            self.dirName = DirName(archive.archiveDir)
            self.archive.postProcessor = self
            self.archiveName = archiveName(self.dirName)

        self.nzbFileName = None
        if self.isNZBArchive():
            self.nzbFileName = archive.nzbFileName

        # Whether or not this thread is the only thing happening in the app (-Lp mode)
        self.background = background
        
        # If we're a background Post Processor, our MO is to move dirName to DEST_DIR when
        # finished (successfully or not)
        self.movedDestDir = False

        # Whether all par data for the NZB has not been downloaded. If this is True,
        # and par fails needing more data, we can trigger a download of extra par dat
        self.hasMorePars = False
        if self.isNZBArchive() and self.archive.skippedParSubjects:
            self.hasMorePars = True
        
        self.decompressionThreadPool = []
        self.decompressorLock = RLock()
        self.decompressorCondition = Condition(self.decompressorLock)

        self.musicFiles = []
        self.brokenFiles = []
        self.movedSamples = []

        self.msgId = None
        self.startTime = None

        # Failed decompress threads put their file names in this list
        self.failedLock = Lock()
        self.failedToProcesses = []
        
        # Whether or not this PostProcessor's Topen processes were explicitly kill()'ed
        self.killed = False

        # Whether or not this post processor will call back to the twisted thread to force
        # a par recovery download
        self.forcedRecovery = False
        # Function to call the twisted thread to force a par recovery download
        self.callback = None
    
        Thread.__init__(self)

    def __getattr__(self, name):
        """ Forward specific attribute lookups to the Archive object """
        if name in self.archiveAttrs:
            return getattr(self.archive, name)
        raise AttributeError, name

    def __setattr__(self, name, value):
        """ Forward specific attribute setting to the Archive object """
        if name in self.archiveAttrs:
            setattr(self.archive, name, value)
        else:
            self.__dict__[name] = value

    def getName(self):
        """ The name of the archive currently being post processed """
        return os.path.basename(self.dirName)

    def isNZBArchive(self):
        """ Whether or not the current archive was downloaded from an NZB file """
        from Hellanzb.NZBLeecher.NZBModel import NZB # FIXME:
        return isinstance(self.archive, NZB)
        
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
        moveBackSamples(self)
        
        if not self.forcedRecovery:
            cleanUp(self.dirName)

        if not self.isSubDir:
            Hellanzb.postProcessorLock.acquire()
            Hellanzb.postProcessors.remove(self)
            self.archive.postProcessor = None
            Hellanzb.postProcessorLock.release()

            # Write the queue to disk unless we've been stopped by a killed Topen (via
            # CTRL-C)
            if not self.killed and not self.isSubDir and self.background:
                Hellanzb.writeStateXML()

        # FIXME: This isn't the best place to GC. The best place would be when a download
        # is finished (idle NZBLeecher) but with smartpar, finding an idle NZBLeecher is
        # tricky
        if not self.isSubDir and self.isNZBArchive():
            self.archive.finalize(self.forcedRecovery)
            if not self.forcedRecovery:
                del self.archive
            gc.collect()

            if self.forcedRecovery:
                self.callback()
                return
            
        # When a Post Processor fails, we end up moving the destDir here
        self.moveDestDir() 

        if not self.background and not self.isSubDir:
            # We're not running in the background of a downloader -- we're post processing
            # and then immeidately exiting (-Lp)
            from twisted.internet import reactor
            reactor.callFromThread(reactor.stop)

    def moveDestDir(self):
        """ Move the archive dir out of PROCESSING_DIR """
        if self.movedDestDir or Hellanzb.SHUTDOWN:
            return
        
        if self.background and not self.isSubDir and \
                os.path.normpath(os.path.dirname(self.dirName.rstrip(os.sep))) == \
                os.path.normpath(Hellanzb.PROCESSING_DIR):

            if os.path.islink(self.dirName):
                # A symlink in the processing dir, remove it
                os.remove(self.dirName)

            elif os.path.isdir(self.dirName):
		if not os.path.isdir(os.path.join(Hellanzb.DEST_DIR, self.category)):
            		try:
               			os.makedirs(os.path.join(Hellanzb.DEST_DIR, self.category))
            		except OSError, ose:
                		raise FatalError('Unable to create directory for category: ' + \
                                os.path.join(Hellanzb.DEST_DIR, self.category)  + \
				' error: ' + str(ose))                
		# A dir in the processing dir, move it to DEST
                newdir = os.path.join(Hellanzb.DEST_DIR, self.category, os.path.basename(self.dirName))
                hellaRename(newdir)
                move(self.dirName, newdir)
                
        self.movedDestDir = True
    
    def run(self):
        """ do the work """
        if not self.isSubDir:
            Hellanzb.postProcessorLock.acquire()
            # FIXME: could block if there are too many processors going
            Hellanzb.postProcessors.append(self)
            Hellanzb.postProcessorLock.release()

            if not self.isSubDir and self.background:
                Hellanzb.writeStateXML()
        
        try:
            self.postProcess()
            
        except SystemExit, se:
            # REACTOR STOPPED IF NOT BACKGROUND/SUBIDR
            self.stop()
            
            if self.isSubDir:
                # Propagate up to the original Post Processor
                raise

            return
        
        except FatalError, fe:
            # REACTOR STOPPED IF NOT BACKGROUND/SUBIDR
            if self.background:
                logStateXML(debug)
            self.stop()

            # Propagate up to the original Post Processor
            if self.isSubDir:
                raise

            pe = prettyException(fe)
            lines = pe.split('\n')
            archive = archiveName(self.dirName)
            if self.background and Hellanzb.LOG_FILE and len(lines) > 13:
                # Show only the first 4 and last 4 lines of the error
                begin = ''.join([line + '\n' for line in lines[:3]])
                end = ''.join([line + '\n' for line in lines[-9:]])
                msg = begin + \
                    '\n <hellanzb truncated the error\'s output, see the log file for full output>\n' + \
                    end
                
                noLogFile(archive + ': A problem occurred: ' + msg)
                logFile(archive + ': A problem occurred', fe)
            else:
                error(archive + ': A problem occurred: ' + pe)

            e = time.time() - self.startTime 
            dispatchExternalHandler(ERROR, archiveName=archive,
                                    destDir=os.path.join(Hellanzb.DEST_DIR, self.category, archive),
                                    elapsedTime=prettyElapsed(e),
                                    parMessage='A problem occurred: %s' % pe)

            return
        
        except Exception, e:
            # REACTOR STOPPED IF NOT BACKGROUND/SUBIDR
            if self.background:
                logStateXML(debug)
            self.stop()
            
            # Propagate up to the original Post Processor
            if self.isSubDir:
                raise
            
            error(archiveName(self.dirName) + ': An unexpected problem occurred', e)
            return

        # REACTOR STOPPED IF NOT BACKGROUND/SUBIDR
        self.stop() # successful post process
    
    def processMusic(self):
        """ Assume the integrity of the files in the specified directory have been
        verified. Iterate through the music files, and decompres them when appropriate in
        multiple threads """
        if not isFreshState(self.dirName, 'music'):
            info(archiveName(self.dirName) + ': Skipping music file decompression')
            return
        
        # Determine the music files to decompress
        musicTypes = []
        for file in os.listdir(self.dirName):
            absPath = os.path.join(self.dirName, file)
            musicType = getMusicType(file)
            if os.path.isfile(absPath) and musicType and musicType.shouldDecompress():
                self.musicFiles.append(absPath)
                if musicType not in musicTypes:
                    musicTypes.append(musicType)
        musicTypes.sort()
    
        if len(self.musicFiles) == 0:
            return

        self.musicFiles.sort()

        threadCount = min(len(self.musicFiles), int(Hellanzb.MAX_DECOMPRESSION_THREADS))
        
        filesTxt = 'file'
        threadsTxt = 'thread'
        musicTypesPrefix = 'format'
        if len(self.musicFiles) != 1:
            filesTxt += 's'
        if threadCount != 1:
            threadsTxt += 's'
        if len(musicTypes) > 1:
            musicTypesPrefix += 's'

        fileCount = len(self.musicFiles)
        musicTypesTxt = ', '.join([musicType.extension for musicType in musicTypes])
        info('%s: Decompressing %i %s (%s: %s) via %i %s..' % \
             (archiveName(self.dirName), fileCount, filesTxt, musicTypesPrefix, musicTypesTxt,
              threadCount, threadsTxt))
        start = time.time()
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
        self.decompressorLock.acquire()
        decompressorThreads = self.decompressionThreadPool[:]
        self.decompressorLock.release()
        
        for decompressor in decompressorThreads:
            decompressor.join()

        del decompressorThreads
        checkShutdown()

        if len(self.failedToProcesses) > 0:
            raise FatalError('Failed to complete music decompression')

        processComplete(self.dirName, 'music', None)

        e = time.time() - start
        info('%s: Finished decompressing (%i %s, took: %s)' % (archiveName(self.dirName),
                                                               fileCount, filesTxt,
                                                               prettyElapsed(e)))

    def finishedPostProcess(self):
        """ finish the post processing work """
        moveBackSamples(self)

        # Move other cruft out of the way
        deleteDuplicates(self.dirName)
        
        # Move out anything else that's broken, a dupe or tagged as
        # not required
        for file in self.brokenFiles:
            if os.path.isfile(os.path.join(self.dirName, file)):
                move(os.path.join(self.dirName, file),
                     os.path.join(self.dirName, Hellanzb.PROCESSED_SUBDIR, file))

        for file in os.listdir(self.dirName):
            ext = getFileExtension(file)
            if ext is not None and len(ext) > 0 and \
                    ext.lower() not in Hellanzb.KEEP_FILE_TYPES and \
                   ext.lower() in Hellanzb.NOT_REQUIRED_FILE_TYPES:
                move(os.path.join(self.dirName, file),
                     os.path.join(self.dirName, Hellanzb.PROCESSED_SUBDIR, file))
                
            elif re.match(r'.*_duplicate\d{0,4}', file):
                move(os.path.join(self.dirName, file),
                     os.path.join(self.dirName, Hellanzb.PROCESSED_SUBDIR, file))

        handledPars = False
        if os.path.isfile(os.path.join(self.dirName, Hellanzb.PROCESSED_SUBDIR, '.par_done')):
            handledPars = True
        
        # Finally, nuke the processed dir. Hopefully the PostProcessor did its job and
        # there was absolutely no need for any of the files in the processed dir,
        # otherwise tough! (otherwise disable the option and redownload again)
        deleteDir = os.path.join(self.dirName, Hellanzb.PROCESSED_SUBDIR)
        deletedFiles = walk(deleteDir, 1, return_folders = 1)
        deletedFiles.sort()
        deletedFiles = [fileName.replace(deleteDir + os.sep, '') for fileName in deletedFiles]

        if hasattr(Hellanzb, 'DELETE_PROCESSED') and Hellanzb.DELETE_PROCESSED:
            msg = 'Deleting processed dir: ' + \
                os.path.join(archiveName(self.dirName), Hellanzb.PROCESSED_SUBDIR) + \
                ', it contains: ' + str(deletedFiles) + '\n'
            if len(deletedFiles):
                logFile(msg)
            rmtree(os.path.join(self.dirName, Hellanzb.PROCESSED_SUBDIR))

        # Finished. Move dirName to DEST_DIR if we need to
        self.moveDestDir()
        
        # We're done
        e = time.time() - self.startTime 
        if not self.isSubDir:
            parMessage = ''
            if not handledPars:
                parMessage = ' (No Pars)'
            totalTime = ''
            if self.isNZBArchive():
                totalTime = ' (total: %s)' % prettyElapsed(e + self.archive.downloadTime)

            elapsed = prettyElapsed(e)
            archive = archiveName(self.dirName)
            info('%s: Finished processing (took: %s)%s%s' % (archive, 
                                                           elapsed, totalTime, parMessage))
            dispatchExternalHandler(SUCCESS, archiveName=archive,
                                    destDir=os.path.join(Hellanzb.DEST_DIR, self.category, archive),
                                    elapsedTime=prettyElapsed(e),
                                    parMessage=parMessage)

            if parMessage != '':
                parMessage = '\n' + parMessage
            growlNotify('Archive Success', 'hellanzb Done Processing%s:' % parMessage,
                        '%s\ntook: %s%s' % (archive, elapsed, totalTime), True)
                       #self.background)
        # FIXME: could unsticky the message if we're running hellanzb.py -p
        # and preferably if the post processing took say over 30 seconds

    def postProcess(self):
        """ process the specified directory """
        # Check for shutting down flag before doing any significant work
        self.startTime = time.time()
        checkShutdown()
        
        # Put files we've processed and no longer need (like pars rars) in this dir
        processedDir = os.path.join(self.dirName, Hellanzb.PROCESSED_SUBDIR)

        if not os.path.exists(self.dirName):
            raise FatalError('Directory does not exist: ' + self.dirName)
        elif not os.path.isdir(self.dirName):
            raise FatalError('Not a directory: ' + self.dirName)
                              
        if not os.path.exists(processedDir):
            try:
                os.mkdir(processedDir)
            except OSError, ose:
                # We might have just unrared something with goofy permissions.
                
                # FIXME: hope we don't need the processed dir! this would typically only
                # happen for say a VIDEO_TS dir anyway
                warn('Unable to create processedDir: ' + processedDir + ' err: ' + str(ose))
                pass

                # FIXME: If we just unrared a directory bad perms, ideally we should fix
                # the perms
                #if ose.errno == errno.EACCES:
                #    os.chmod(processedDir, 

        elif not os.path.isdir(processedDir):
            raise FatalError('Unable to create processed dir, a non dir already exists there: ' + \
                             processedDir)
    
        # First, find broken files, in prep for repair. Grab the msg id while we're at it
        files = os.listdir(self.dirName)
        for file in files:
            absoluteFile = os.path.join(self.dirName, file)
            if os.path.isfile(absoluteFile):
                if file.endswith('_broken'):
                    # Keep track of the broken files
                    self.brokenFiles.append(absoluteFile)
                    
                elif len(file) > 7 and file[0:len('.msgid_')] == '.msgid_':
                    self.msgId = file[len('.msgid_'):]
    
        # If there are required broken files and we lack pars, punt
        if len(self.brokenFiles) > 0 and containsRequiredFiles(self.brokenFiles) and \
                not dirHasPars(self.dirName):
            errorMessage = 'Unable to process directory: ' + self.dirName + '\n' + \
                'This directory has the following broken files: '
            for brokenFile in self.brokenFiles:
                errorMessage += '\n' + ' '*4 + brokenFile
            errorMessage += '\nand contains no par2 files for repair'
            raise FatalError(errorMessage)

        # Find any files that need to assembled (e.g. file.avi.001, file.avi.002)
        needAssembly = findSplitFiles(self.dirName)
        
        foundPars = False
        if dirHasPars(self.dirName):
            foundPars = True
            
            checkShutdown()
            try:
                processPars(self, needAssembly)
            except ParExpectsUnsplitFiles:
                info(archiveName(self.dirName) + ': This archive requires assembly before running par2')
                decodeMacBin(self)
                assembleSplitFiles(self.dirName, needAssembly)
                try:
                    processPars(self, None)
                except NeedMorePars, nmp:
                    if self.triggerParRecovery(nmp):
                        return
            except NeedMorePars, nmp:
                if self.triggerParRecovery(nmp):
                    return

        cleanSkippedPars(self.dirName)

        if self.background and not self.isSubDir and \
                os.path.isfile(os.path.join(self.dirName, Hellanzb.PROCESSED_SUBDIR,
                                            '.par_done')):
            cleanHellanzbTmpFiles(self.dirName)
        
        # Rars may need assembly before unraring
        decodeMacBin(self)
        assembleSplitFiles(self.dirName, findSplitFiles(self.dirName))

        if not Hellanzb.SKIP_UNRAR and dirHasRars(self.dirName):
            checkShutdown()
            moveSamples(self)
            processRars(self)

        if dirHasMusic(self.dirName):
            checkShutdown()
            self.processMusic()

        # Assemble split up files (that were just unrared)
        decodeMacBin(self)
        assembleSplitFiles(self.dirName, findSplitFiles(self.dirName))

        # FIXME: do we need to gc.collect() after post processing a lot of data?

        # Post process sub directories
        trolled = 0
        for file in os.listdir(self.dirName):
            if file == Hellanzb.PROCESSED_SUBDIR:
                continue
            
            if os.path.isdir(pathjoin(self.dirName, file)):
                if not self.isSubDir:
                    troll = PostProcessor(self.archive, background = self.background,
                                          subDir = file)
                else:
                    troll = PostProcessor(self.archive, background = self.background,
                                          subDir = pathjoin(self.subDir, file))
                troll.run()
                trolled += 1

        if foundPars:
            cleanDupeFiles(self.dirName)
                
        self.finishedPostProcess()

    def triggerParRecovery(self, nmp):
        """ Trigger a par recovery download for the specified NeedMorePars exception """
        if self.background and self.isNZBArchive() and self.hasMorePars:
            # Must download more pars. Move the archive to the postponed dir, and
            # triggere the special force call for par recoveries
            postponedDir = os.path.join(Hellanzb.POSTPONED_DIR,
                                        os.path.basename(self.dirName))
            move(self.dirName, postponedDir)
            self.archive.archiveDir = self.archive.destDir = postponedDir
            self.archive.nzbFileName = \
                os.path.join(postponedDir, os.path.basename(self.archive.nzbFileName))

            info(archiveName(self.dirName) + \
                 ': More pars available, forcing extra par download')

            self.archive.neededBlocks, self.archive.parType, self.archive.parPrefix = \
                nmp.size, nmp.parType, nmp.parPrefix
            self.forcedRecovery = True

            def triggerRecovery():
                from twisted.internet import reactor
                from Hellanzb.Daemon import forceNZBParRecover # FIXME:
                reactor.callFromThread(forceNZBParRecover, self.archive)
            self.callback = triggerRecovery
            return True
        else:
            info(archiveName(self.dirName) + ': Failed par verify, requires ' + \
                 nmp.neededBlocks + ' more recovery ' + \
                 getParRecoveryName(nmp.parType))
        return False

"""
Copyright (c) 2005 Philip Jenvey <pjenvey@groovie.org>
                   Ben Bangert <bbangert@groovie.org>
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions
are met:
1. Redistributions of source code must retain the above copyright
   notice, this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright
   notice, this list of conditions and the following disclaimer in the
   documentation and/or other materials provided with the distribution.
3. The name of the author or contributors may not be used to endorse or
   promote products derived from this software without specific prior
   written permission.

THIS SOFTWARE IS PROVIDED BY THE AUTHOR AND CONTRIBUTORS ``AS IS'' AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED.  IN NO EVENT SHALL THE AUTHOR OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS
OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY
OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
SUCH DAMAGE.

$Id$
"""
