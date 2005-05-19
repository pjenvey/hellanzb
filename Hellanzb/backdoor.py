# -*- Mode: Python; tab-width: 4 -*-

# Copyright 1999, 2000 by eGroups, Inc, Itamar Shtull-Trauring
# 
#                         All Rights Reserved
# 
# Permission to use, copy, modify, and distribute this software and
# its documentation for any purpose and without fee is hereby
# granted, provided that the above copyright notice appear in all
# copies and that both that copyright notice and this permission
# notice appear in supporting documentation, and that the name of
# eGroups not be used in advertising or publicity pertaining to
# distribution of the software without specific, written prior
# permission.
# 
# EGROUPS DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE,
# INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS, IN
# NO EVENT SHALL EGROUPS BE LIABLE FOR ANY SPECIAL, INDIRECT OR
# CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
# OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT,
# NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN
# CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

VERSION_STRING = '$ORIGId: backdoor.py,v 1.4 2001/01/02 15:25:09 itamar Exp itamar $'

import socket
import string
import StringIO
import sys
import traceback


class backdoor:

    def __init__ (self, socket, line_separator='\r\n'):
        self.socket = socket
        self.buffer = ''
        self.lines = []
        self.multilines = []
        self.line_separator = line_separator

        # allow the user to change the prompts:
        if not sys.__dict__.has_key('ps1'):
            sys.ps1 = '>>> '
        if not sys.__dict__.has_key('ps2'):
            sys.ps2 = '... '

    def send (self, data):
        olb = lb = len(data)
        while lb:
            ns = self.socket.send (data)
            lb = lb - ns
        return olb
        
    def prompt (self):
        if self.multilines:
            self.send (sys.ps2)
        else:
            self.send (sys.ps1)

    def read_line (self):
        if self.lines:
            l = self.lines[0]
            self.lines = self.lines[1:]
            return l
        else:
            while not self.lines:
                block = self.socket.recv (8192)
                if not block:
                    return None
                elif block == '\004':
                    self.socket.close()
                    return None
                else:
                    self.buffer = self.buffer + block
                    lines = string.split (self.buffer, self.line_separator)
                    for l in lines[:-1]:
                        self.lines.append (l)
                    self.buffer = lines[-1]
            return self.read_line()
        
    def read_eval_print_loop (self):
        self.send ('Python ' + sys.version + self.line_separator)
        self.send (sys.copyright + self.line_separator)
        # this does the equivalent of 'from __main__ import *'
        env = sys.modules['__main__'].__dict__.copy()
        while 1:
            self.prompt()
            line = self.read_line()
            if line is None:
                break
            elif self.multilines:
                self.multilines.append(line)
                if line == '':
                    code = string.join(self.multilines, '\n')
                    self.parse(code, env)
                    # we do this after the parsing so parse() knows not to do
                    # a second round of multiline input if it really is an
                    # unexpected EOF
                    self.multilines = []
            else:
                self.parse(line, env)

    def parse(self, line, env):
        save = sys.stdout, sys.stderr
        output = StringIO.StringIO()
        try:
            try:
                sys.stdout = sys.stderr = output
                co = compile (line, repr(self), 'eval')
                result = eval (co, env)
                if result is not None:
                    print repr(result)
                    env['_'] = result
            except SyntaxError:
                try:
                    co = compile (line, repr(self), 'exec')
                    exec co in env
                except SyntaxError, msg:
                    # this is a hack, but it is a righteous hack
                    # it's also not very forward compatible
                    if not self.multilines and str(msg)[:28] == 'unexpected EOF while parsing':
                        self.multilines.append(line)
                    else:
                        traceback.print_exc()
                except:
                    traceback.print_exc()
            except:
                traceback.print_exc()
        finally:
            sys.stdout, sys.stderr = save
            self.send (output.getvalue())
            del output

def client (conn, addr):
    b = backdoor(conn)
    b.read_eval_print_loop()

def serve (host='127.0.0.1', port=8023):
    s = socket.socket (socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt (
            socket.SOL_SOCKET, socket.SO_REUSEADDR,
            s.getsockopt (socket.SOL_SOCKET, socket.SO_REUSEADDR) | 1
        )
    except:
        pass
    
    s.bind ((host, port))
    s.listen(5)
    while 1:
        conn, addr = s.accept()
        print 'incoming connection from', addr
        client(conn, addr)

if __name__ == '__main__':
    serve()
