#!/usr/local/bin/python
"""
Module: ziplick.py
Author: Ben Bangert
Date: 9/25/04

version 0.1

Instructions for use:
This software expects a layout looking roughly like the following
 mainfolder/
     nzb/             -- nzb processing, put ziplick in here
	     working/        -- working directory for nzbget (set this in your nzbget rc file)
		 queue/          -- drag your nzb files to this dir to be queued
		 current/        -- don't mess with this, its the current nzb file being worked on
		 temp/           -- temp space for nzbget (set this in your nzbget rc file)
     usenet/          -- final directory that fetched nzb's end up in

These can be customized below. Killing ziplick in the middle of processing should have
no effect as it will start on the current nzbfile again when spawned.

# FIXME: ziplick, now that it's a thread, (all hellanzb threads actually) aren't handling
# keyboard interrupts, they need to detect them and notify their parent

# TODO: the queue daemon should also monitor files in the final directory, for those that
# require a rar password. when a password is found it will recall Troll to finish
# extracting

To install/run
1) Create folder heiarchy as shown above
2) Put ziplick.py wherever
3) Run: ziplick.py (after chmod +x it)
4) Drop nzb files into the queue dir
"""

import Hellanzb, os, re, Troll
from time import sleep
from threading import Thread
from Troll import FatalError, info, growlNotify, stringEndsWith, touch

__id__ = "$Id"

class Ziplick(Thread):

        def __init__(self):
                self.ensureDirs()
                Thread.__init__(self)

        def ensureDirs(self):
                """ Ensure that all the required directories exist, otherwise attempt to create them """
                for arg in dir(Hellanzb):
                        if stringEndsWith(arg, "_DIR") and arg == arg.upper():

                                exec 'dir = Hellanzb.' + arg
                                if not os.path.isdir(dir):
                                        try:
                                                os.mkdir(dir)
                                        except AccessError:
                                                raise FatalError("Unable to create Hellanzb DIRs")
                                                


        def archiveNameFromNzb(self, nzbFileName):
                """ Strip the msg_id and .nzb extension from an nzb file name """
                nzbFileName = re.sub(r'msgid_.*?_',r'',nzbFileName)
                return re.sub(r'\.nzb$',r'',nzbFileName)
                
        def run(self):
                self.queued_nzbs = []
                self.current_nzbs = [x for x in os.listdir(Hellanzb.CURRENT_DIR) if re.search(r'\.nzb$',x)]

                growlNotify('Queue', 'hellanzb', 'Now monitoring queue..')
                while 1:
                	# See if we're resuming a nzb fetch
                	if not self.current_nzbs:
                
                		# Refresh our queue and append the new nzb's, 
                		new_nzbs = [x for x in os.listdir(Hellanzb.QUEUE_DIR) \
                                            if x not in self.queued_nzbs and re.search(r'\.nzb$',x)]

                                if len(new_nzbs) > 0:
                                        self.queued_nzbs.extend(new_nzbs)
                                        self.queued_nzbs.sort()
                                        for nzb in new_nzbs:
                                                msg = 'Found new nzb:'
                                                info(msg + self.archiveNameFromNzb(nzb))
                                                growlNotify('Queue', 'hellanzb ' + msg, \
                                                            self.archiveNameFromNzb(nzb))
                
                		# Nothing to do, lets wait 5 seconds and start over
                		if not self.queued_nzbs:
                			sleep(5)
                			continue
                
                		nzbfilename = self.queued_nzbs[0]
                		del self.queued_nzbs[0]
                
                		# Fix the filename
                		newname = re.sub(r'[\[|\]|\(|\)]',r'',nzbfilename)
                		os.rename(Hellanzb.QUEUE_DIR+nzbfilename,Hellanzb.QUEUE_DIR+newname)
                		nzbfilename = newname
                
                		# nzbfile will always be a absolute filename 
                		nzbfile = Hellanzb.QUEUE_DIR + nzbfilename
                		os.spawnlp(os.P_WAIT, 'mv', 'mv', nzbfile, Hellanzb.CURRENT_DIR)
                	else:
                		nzbfilename = self.current_nzbs[0]
                                growlNotify('Queue', 'hellanzb Resuming:', self.archiveNameFromNzb(nzb))
                		del self.current_nzbs[0]
                	nzbfile = Hellanzb.CURRENT_DIR + nzbfilename
                
                	# Run nzbget to fetch the current nzbfile
                	result = os.spawnlp(os.P_WAIT, 'nzbget', 'nzbget', nzbfile)
                
                	# Make our new directory, minus the .nzb
                	newdir = Hellanzb.DEST_DIR + nzbfilename
                        
                        # Grab the message id, we'll store it in the newdir for later use
                        msgId = re.sub(r'.*msgid_', r'', newdir)
                        msgId = re.sub(r'_.*', r'', msgId)
                                       
                        newdir = self.archiveNameFromNzb(newdir)
                
                	# Take care of the unfortunate case that we coredumped
                        coreFucked = False
                	if os.WCOREDUMP(result):
                                coreFucked = True
                		newdir = newdir + '_corefucked'
                
                	# Move our nzb contents to their new location, clear out the temp dir
                        # FIXME: rename actually sucks here -- it blows up if you're
                        # renaming a file to a different mount point
                	os.rename(Hellanzb.WORKING_DIR,newdir)
                        touch(newdir + os.sep + '.msgid_' + msgId)
                	os.spawnlp(os.P_WAIT, 'mv', 'mv', nzbfile, newdir)
                	os.mkdir(Hellanzb.WORKING_DIR)

                        # Finally unarchive/process the directory
                        if not coreFucked:
                                Troll.init()
                                Troll.troll(newdir)
