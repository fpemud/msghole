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
    #   on_command_XXX(self, data)
    #   on_notification_XXX(self, data)
    #   on_error(self, excp)
    #   on_close(self)
    #
    # exception in on_command_XXX(), command_XXX_return_callback(), command_XXX_error_callback(), on_notification_XXX() would close the object
    # no exception is allowed in on_error(), on_close().
    # exec_command() and send_notification() should not be called in on_error() and on_close().
    # close(immediate=True) should not be called in on_XXX().
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

    def close(self, immediate=False):
        assert self.iostream is not None
        self._pre_close()
        if not immediate:
            self.idle_close = GLib.idle_add(self._close)
        else:
            self._close()

    def send_notification(self, notification, data):
        jsonObj = dict()
        jsonObj["notification"] = notification
        if data is not None:
            jsonObj["data"] = data
        if self.idle_close is None:
            self.dos.put_string(json.dumps(jsonObj) + "\n")

    def exec_command(self, command, data=None, return_callback=None, error_callback=None):
        assert self.command_sent is None

        jsonObj = dict()
        jsonObj["command"] = command
        if data is not None:
            jsonObj["data"] = data
        if self.idle_close is None:
            self.dos.put_string(json.dumps(jsonObj) + "\n")
        self.command_sent = (command, return_callback, error_callback)

    def _on_receive(self, source_object, res):
        try:
            line, len = source_object.read_line_finish_utf8(res)
            if line is None:
                raise PeerCloseError()

            self.dis.read_line_async(0, self.canceller, self._on_receive)

            jsonObj = json.loads(line)

            if "command" in jsonObj:
                if self.command_received is not None:
                    raise Exception("unexpected \"command\" message")
                funcname = "on_command_" + jsonObj["command"].replace("-", "_")
                if not hasattr(self, funcname):
                    raise Exception("no callback for command " + jsonObj["command"])
                self.command_received = jsonObj["command"]
                getattr(self, funcname)(jsonObj.get("data", None), self._send_return, self._send_error)
                return

            if "notification" in jsonObj:
                funcname = "on_notification_" + jsonObj["notification"].replace("-", "_")
                if not hasattr(self, funcname):
                    raise Exception("no callback for notification " + jsonObj["notification"])
                getattr(self, funcname)(jsonObj.get("data", None))
                return

            if "return" in jsonObj:
                if self.command_sent is None:
                    raise Exception("unexpected \"return\" message")
                cmd, return_cb, error_cb = self.command_sent
                self.command_sent = None
                if return_cb is None:
                    if jsonObj["return"] is not None:
                        raise Exception("no return callback specified for command " + cmd)
                else:
                    return_cb(jsonObj["return"])
                return

            if "error" in jsonObj:
                if self.command_sent is None:
                    raise Exception("unexpected \"error\" message")
                cmd, return_cb, error_cb = self.command_sent
                self.command_sent = None
                if error_cb is None:
                    raise Exception("no error callback specified for command " + cmd)
                else:
                    error_cb(jsonObj["error"])
                return

            raise Exception("invalid message")
        except Exception as e:
            assert not isinstance(e, BusinessException)
            assert self.idle_close is None
            self.on_error(e)
            self._pre_close()
            self._close()

    def _send_return(self, data):
        assert self.command_received is not None

        jsonObj = dict()
        jsonObj["return"] = data
        if self.idle_close is None:
            self.dos.put_string(json.dumps(jsonObj) + "\n")
        self.command_received = None

    def _send_error(self, data):
        assert self.command_received is not None

        jsonObj = dict()
        jsonObj["error"] = data
        if self.idle_close is None:
            self.dos.put_string(json.dumps(jsonObj) + "\n")
        self.command_received = None

    def _pre_close(self):
        self.canceller.cancel()
        self.canceller = None
        self.iostream.close()
        self.iostream = None
        self.dis = None
        self.dos = None

    def _close(self):
        self.on_close()
        self.command_received = None
        self.command_sent = None
        self.idle_close = None


class BusinessException(Exception):
    pass


class PeerCloseError(Exception):
    pass
