#!/usr/bin/env python3

# Copyright (c) 2005-2017 Fpemud <fpemud@sina.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

"""
msghole

@author: Fpemud
@license: GPLv3 License
@contact: fpemud@sina.com
"""

import json
from gi.repository import Gio
from gi.repository import GLib

__author__ = "fpemud@sina.com (Fpemud)"
__version__ = "0.0.1"


class EndPoint:
    # sub-class must implement the following functions:
    #   on_command_XXX_return(self, data)
    #   on_command_XXX_error(self, reason)
    #   on_notification_XXX(self, data)
    #   on_error(self, excp)
    #   on_close(self)
    #
    # exception in on_command_XXX_return(), on_command_XXX_error(), on_notification_XXX() would close the object and iostream
    # no exception is allowed in on_error(), on_close().
    # close(), send_notification(), exec_command() should not be called in on_XXX().
    # This class is not thread-safe.

    def __init__(self):
        self.iostream = None
        self.dis = None
        self.dos = None
        self.canceller = None
        self.command_received = None
        self.command_sent = None
        self.idle_close = None

    def set_iostream_and_start(self, iostream):
        assert self.iostream is None

        try:
            self.iostream = iostream
            self.dis = Gio.DataInputStream.new(iostream.get_input_stream())
            self.dos = Gio.DataOutputStream.new(iostream.get_output_stream())
            self.canceller = Gio.Cancellable()
            self.dis.read_line_async(0, self.canceller, self._on_receive)     # fixme: 0 should be PRIORITY_DEFAULT, but I can't find it
        except:
            self.iostream = None
            self.dis = None
            self.dos = None
            self.canceller = None
            raise

    def close(self):
        if self.iostream is not None:
            if self.idle_close is None:
                self.canceller.cancel()
                self.dis = None
                self.dos = None
                self.canceller = None
                self.idle_close = GLib.idle_add(self._close)
        else:
            assert self.dis is None
            assert self.dos is None
            assert self.canceller is None
            assert self.command_received is None
            assert self.command_sent is None

    def send_notification(self, notification, data):
        jsonObj = dict()
        jsonObj["notification"] = notification
        if data is not None:
            jsonObj["data"] = data
        self.dos.put_string(json.dumps(jsonObj) + "\n")

    def exec_command(self, command, data, return_callback=None, error_callback=None):
        assert self.command_sent is None

        jsonObj = dict()
        jsonObj["command"] = command
        if data is not None:
            jsonObj["data"] = data
        self.dos.put_string(json.dumps(jsonObj) + "\n")
        self.command_sent = (command, return_callback, error_callback)

    def _on_receive(self, source_object, res):
        try:
            line, len = source_object.read_line_finish_utf8(res)
            if line is None:
                raise Exception("socket closed by peer")

            jsonObj = json.loads(line)
            while True:
                if "command" in jsonObj:
                    if self.command_received is not None:
                        raise Exception("unexpected \"command\" message")
                    funcname = "on_command_" + jsonObj["command"].replace("-", "_")
                    if not hasattr(self, funcname):
                        raise Exception("no callback for command " + jsonObj["command"])
                    self.command_received = jsonObj["command"]
                    getattr(self, funcname)(jsonObj.get("data", None), self._send_return, self._send_error)
                    break

                if "notification" in jsonObj:
                    funcname = "on_notification_" + jsonObj["notification"].replace("-", "_")
                    if not hasattr(self, funcname):
                        raise Exception("no callback for notification " + jsonObj["notification"])
                    getattr(self, funcname)(jsonObj.get("data", None))
                    break

                if "return" in jsonObj:
                    if self.command_sent is None:
                        raise Exception("unexpected \"return\" message")
                    cmd, return_cb, error_cb = self.command_sent
                    if jsonObj["return"] is not None and return_cb is None:
                        raise Exception("no return callback specified for command " + cmd)
                    if return_cb is not None:
                        return_cb(jsonObj["return"])
                    self.command_sent = None
                    break

                if "error" in jsonObj:
                    if self.command_sent is None:
                        raise Exception("unexpected \"error\" message")
                    cmd, return_cb, error_cb = self.command_sent
                    if error_cb is None:
                        raise Exception("no error callback specified for command " + cmd)
                    error_cb(jsonObj["error"])
                    self.command_sent = None
                    break

                raise Exception("invalid message")

            self.dis.read_line_async(0, self.canceller, self._on_receive)
        except Exception as e:
            self.on_error(e)
            self._close()

    def _send_return(self, data):
        assert self.command_received is not None

        jsonObj = dict()
        jsonObj["return"] = data
        self.dos.put_string(json.dumps(jsonObj) + "\n")
        self.command_received = None

    def _send_error(self, data):
        assert self.command_received is not None

        jsonObj = dict()
        jsonObj["error"] = data
        self.dos.put_string(json.dumps(jsonObj) + "\n")
        self.command_received = None

    def _close(self):
        assert self.iostream is not None
        assert self.dis is None
        assert self.dos is None
        assert self.canceller is None

        self.on_close()
        self.iostream.close()
        self.iostream = None
        self.command_sent = None
        self.command_received = None
        self.idle_close = None
