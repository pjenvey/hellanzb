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

class MemberFunctions:
    def __init__(self):
        gn = Growl.GrowlNotifier()
        gn.applicationName = 'hellanzb'
        gn.notifications = ['Archive','Queue','Error']
        gn.register()
        self.gn = gn
        
    def notify(self, ntype, title, description, sticky):
        gn = self.gn
        gn.notify(noteType=ntype,title=title,description=description, sticky=sticky)
        return 1
        
# Make our XMLRPC Server, create our instance, and assign it
server = SimpleXMLRPCServer.SimpleXMLRPCServer(("192.168.2.4", 7300))
memfun = MemberFunctions()
server.register_function(memfun.notify)

# Start the server
server.serve_forever()
