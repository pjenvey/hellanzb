#!/usr/bin/python
"""
hellagrowler.py
Date: 9/26/04
Author: Ben Bangert

hellagrowler is a XML-RPC daemon for OSX that delivers messages to the user through
Growl user notification daemon.

For information on Growl: http://growl.info/

INSTRUCTIONS
Before using this, you must have installed several packages in OSX.

1) Install Growl (http://growl.info/downloads.php)
2) Install PyObjC (http://pyobjc.sourceforge.net/)
3) Install the Growl Python Bindings (http://growl.info/downloads.php)
4) Run hellagrowler.py

TODO
o Put all that install crap into a nice OSX Package Installer, and run this as a
  system service.
o Put some basic authentication (require password/secret) so it won't just spit
  out anything from anyone
"""

import Growl
import SimpleXMLRPCServer
from AppKit import NSWorkspace, NSImage
import sys, os.path

iconPath = 'growlerIcons/'
Icons = { 'appIcon' : 'JuandelDiablo.tiff', \
          'nzbCoreFuck' : 'JollyRoger.tiff', \
          'archiveError' : 'Scudmore.tiff', \
          'archiveSuccess' : 'PirateTreasure.tiff' }

class MemberFunctions:
    def __init__(self,Icons):
        gn = Growl.GrowlNotifier()
        gn.applicationName = 'hellanzb'
        gn.applicationIcon = Icons['appIcon']
        gn.notifications = ['Archive Success','Archive Error','Queue','Error']
        gn.register()
        self.gn = gn
        self.Icons = Icons
        
    def notify(self, ntype, title, description, sticky):
        gn = self.gn
        Icons = self.Icons
        nIcon = Icons['appIcon']
        if ntype == 'Archive Success':
            nIcon = Icons['archiveSuccess']
        elif ntype == 'Archive Error':
            nIcon = Icons['archiveError']
        elif ntype == 'Error':
            nIcon = Icons['nzbCoreFuck']
        gn.notify(noteType=ntype,title=title,description=description,icon=nIcon, sticky=sticky)
        return 1

def loadIcons(icons):
    global iconPath
    for icon in icons.keys():
        filename = icons[icon]
        nImagePath = os.path.abspath(iconPath+filename)
        nIcon = NSImage.alloc().initWithContentsOfFile_(nImagePath).autorelease()
        if not nIcon:
            sys.stderr.write("Couldn't load file %s\n" % nImagePath)
        icons[icon] = nIcon
    return icons

Icons = loadIcons(Icons)

# Make our XMLRPC Server, create our instance, and assign it
server = SimpleXMLRPCServer.SimpleXMLRPCServer(("192.168.2.4", 7300))
memfun = MemberFunctions(Icons)
server.register_function(memfun.notify)

# Start the server
server.serve_forever()
