#!/usr/bin/python

import Growl
import SimpleXMLRPCServer

class MemberFunctions:
    def __init__(self):
        gn = Growl.GrowlNotifier()
        gn.applicationName = 'hellanzb'
        gn.notifications = ['Archive','Queue','Error']
        gn.register()
        self.gn = gn
        
    def notify(self, ntype, title, description):
        gn = self.gn
        gn.notify(noteType=ntype,title=title,description=description)
        return 1
        
# Make our XMLRPC Server, create our instance, and assign it
server = SimpleXMLRPCServer.SimpleXMLRPCServer(("192.168.2.4", 7300))
memfun = MemberFunctions()
server.register_function(memfun.notify)

# Start the server
server.serve_forever()
