# killableprocess - subprocesses which can be reliably killed
#
# Parts of this module are copied from the subprocess.py file contained
# in the Python distribution.
#
# Copyright (c) 2003-2004 by Peter Astrand <astrand@lysator.liu.se>
#
# Additions and modifications written by Benjamin Smedberg
# <benjamin@smedbergs.us> are Copyright (c) 2006 by the Mozilla Foundation
# <http://www.mozilla.org/>
#
# By obtaining, using, and/or copying this software and/or its
# associated documentation, you agree that you have read, understood,
# and will comply with the following terms and conditions:
#
# Permission to use, copy, modify, and distribute this software and
# its associated documentation for any purpose and without fee is
# hereby granted, provided that the above copyright notice appears in
# all copies, and that both that copyright notice and this permission
# notice appear in supporting documentation, and that the name of the
# author not be used in advertising or publicity pertaining to
# distribution of the software without specific, written prior
# permission.
#
# THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE,
# INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS.
# IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, INDIRECT OR
# CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS
# OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT,
# NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION
# WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

r"""killableprocess - Subprocesses which can be reliably killed

This module is a subclass of the builtin "subprocess" module. It allows
processes that launch subprocesses to be reliably killed on Windows (via the Popen.kill() method.

It also adds a timeout argument to Wait() for a limited period of time before
forcefully killing the process.

Note: On Windows, this module requires Windows 2000 or higher (no support for
Windows 95, 98, or NT 4.0). It also requires ctypes, which is bundled with
Python 2.5+ or available from http://python.net/crew/theller/ctypes/
"""

import subprocess
import sys
import os
import time
import types
import threading

try:
    from subprocess import CalledProcessError
except ImportError:
    # Python 2.4 doesn't implement CalledProcessError
    class CalledProcessError(Exception):
        """This exception is raised when a process run by check_call() returns
        a non-zero exit status. The exit status will be stored in the
        returncode attribute."""
        def __init__(self, returncode, cmd):
            self.returncode = returncode
            self.cmd = cmd
        def __str__(self):
            return "Command '%s' returned non-zero exit status %d" % (self.cmd, self.returncode)

mswindows = (sys.platform == "win32")
aix5 = (sys.platform == "aix5")

# WEXITED fix
if aix5:
    # AIX 5 has a bug where wait4() doesn't wait for exited processes by 
    # default. wait3() takes whatever options are specified and ORs in the
    # WEXITED option before calling the kwaitpid() function. (kwaitpid()
    # is a syscall that all wait*() functions call).
    #
    # So, we can get around the problem by adding WEXITED ourselves if it
    # exists. We define WEXITED on AIX using the value 4 gotten from sys/wait.h
    #
    # This fix may be necessary on other OSes as well.
    WEXITED = 0x04 # From /usr/include/sys/wait.h
else:
    try:
        # In case this value gets into the os module
        WEXITED = os.WEXITED
    except AttributeError:
        WEXITED = 0

if mswindows:
    import winprocess
else:
    import signal
    import errno

def call(*args, **kwargs):
    waitargs = {}
    if "timeout" in kwargs:
        waitargs["timeout"] = kwargs.pop("timeout")

    return Popen(*args, **kwargs).wait(**waitargs)

def check_call(*args, **kwargs):
    """Call a program with an optional timeout. If the program has a non-zero
    exit status, raises a CalledProcessError."""

    retcode = call(*args, **kwargs)
    if retcode:
        cmd = kwargs.get("args")
        if cmd is None:
            cmd = args[0]
        raise CalledProcessError(retcode, cmd)

class Popen(subprocess.Popen):
    if not mswindows:
        # Override __init__ to set a preexec_fn
        def __init__(self, *args, **kwargs):
            if len(args) >= 7:
                raise Exception("Arguments preexec_fn and after must be passed by keyword.")

            real_preexec_fn = kwargs.pop("preexec_fn", None)
            def setpgid_preexec_fn():
                os.setpgid(0, 0)
                if real_preexec_fn:
                    apply(real_preexec_fn)

            kwargs['preexec_fn'] = setpgid_preexec_fn

            # DLADD kam 04Dec07 Add real, user and system timings
            self._starttime = time.time()
            self.rtime = 0.0
            self.utime = 0.0
            self.stime = 0.0

            subprocess.Popen.__init__(self, *args, **kwargs)

    if mswindows:
        def _execute_child(self, args, executable, preexec_fn, close_fds,
                           cwd, env, universal_newlines, startupinfo,
                           creationflags, shell,
                           p2cread, p2cwrite,
                           c2pread, c2pwrite,
                           errread, errwrite):

            # DLADD kam 04Dec07 Add real, user and system timings
            self._starttime = time.time()
            self.rtime = 0.0
            self.utime = 0.0
            self.stime = 0.0

            if not isinstance(args, types.StringTypes):
                args = subprocess.list2cmdline(args)

            if startupinfo is None:
                startupinfo = winprocess.STARTUPINFO()

            if None not in (p2cread, c2pwrite, errwrite):
                startupinfo.dwFlags |= winprocess.STARTF_USESTDHANDLES
                
                startupinfo.hStdInput = int(p2cread)
                startupinfo.hStdOutput = int(c2pwrite)
                startupinfo.hStdError = int(errwrite)
            if shell:
                startupinfo.dwFlags |= winprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = winprocess.SW_HIDE
                comspec = os.environ.get("COMSPEC", "cmd.exe")
                args = comspec + " /c " + args

            # We create a new job for this process, so that we can kill
            # the process and any sub-processes 
            self._job = winprocess.CreateJobObject()

            creationflags |= winprocess.CREATE_SUSPENDED
            creationflags |= winprocess.CREATE_UNICODE_ENVIRONMENT

            hp, ht, pid, tid = winprocess.CreateProcess(
                executable, args,
                None, None, # No special security
                1, # Must inherit handles!
                creationflags,
                winprocess.EnvironmentBlock(env),
                cwd, startupinfo)
            
            self._child_created = True
            self._handle = hp
            self._thread = ht
            self.pid = pid

            winprocess.AssignProcessToJobObject(self._job, hp)
            winprocess.ResumeThread(ht)

            if p2cread is not None:
                p2cread.Close()
            if c2pwrite is not None:
                c2pwrite.Close()
            if errwrite is not None:
                errwrite.Close()

    def kill(self, group=True):
        """Kill the process. If group=True, all sub-processes will also be killed."""
        if mswindows:
            if group:
                winprocess.TerminateJobObject(self._job, 127)
            else:
                winprocess.TerminateProcess(self._handle, 127)
            self.returncode = 127    
        else:
            if group:
                os.killpg(self.pid, signal.SIGKILL)
            else:
                os.kill(self.pid, signal.SIGKILL)
            self.returncode = -9

    if not mswindows:
        def _wait(self, options):
            """Wait for our pid, gathering resource usage if available"""
            pid, sts, rusage = self._wait4_no_intr(self.pid, options)
            if pid:
                self.rtime = time.time() - self._starttime
                self.utime = rusage[0]
                self.stime = rusage[1]
            return pid, sts

        try:
            _wait4 = os.wait4
        except AttributeError:
            # Don't have wait4 so try wait3 with a check
            # this only works if we are waiting for one process
            @staticmethod
            def _wait4(pid, options):
                rpid, status, rusage = os.wait3(options)
                if rpid and rpid != pid:
                    raise Exception("Waiting for pid %d but unexpected pid %d exited" % (pid, rpid))
                return rpid, status, rusage
                    
        def _wait4_no_intr(self, pid, options):
            """Like os.wait4, but retries on EINTR"""
            while True:
                try:
                    return self._wait4(pid, options | WEXITED)
                except OSError, e:
                    if e.errno == errno.EINTR:
                        continue
                    else:
                        raise

    if mswindows:
        def _getstatus(self):
            self.returncode = winprocess.GetExitCodeProcess(self._handle)

            creation_time, exit_time, kernel_time, user_time = winprocess.GetProcessTimes(self._handle)

            self.rtime = time.time() - self._starttime
            # MS Windows times are in 100ns units, convert to seconds
            self.utime = user_time / 10000000.0
            self.stime = kernel_time / 10000000.0

            return self.returncode
    else:
        def _waitforstatus(self):
            """Wait for child process to terminate.  Returns returncode
            attribute."""
            if self.returncode is None:
                pid, sts = self._wait(0)
                self._handle_exitstatus(sts)
            return self.returncode

    if mswindows:
        def poll(self, _deadstate=None):
            """Check if child process has terminated.  Returns returncode
            attribute."""
            if self.returncode is None:
                if WaitForSingleObject(self._handle, 0) == WAIT_OBJECT_0:
                    self._getstatus()
            return self.returncode
    else:
        def poll(self, _deadstate=None):
            """Check if child process has terminated.  Returns returncode
            attribute."""
            if self.returncode is None:
                try:
                    pid, sts = self._wait(os.WNOHANG)
                    if pid == self.pid:
                        self._handle_exitstatus(sts)
                except os.error:
                    if _deadstate is not None:
                        self.returncode = _deadstate
            return self.returncode


    def wait(self, timeout=-1, group=True):
        """Wait for the process to terminate. Returns returncode attribute.
        If timeout seconds are reached and the process has not terminated,
        it will be forcefully killed. If timeout is -1, wait will not
        time out."""

        if self.returncode is not None:
            return self.returncode

        if mswindows:
            if timeout != -1:
                timeout = int(timeout * 1000)
            rc = winprocess.WaitForSingleObject(self._handle, timeout)
            if rc == winprocess.WAIT_TIMEOUT:
                self.kill(group)
            else:
                self._getstatus()
        else:
            if timeout == -1:
                return self._waitforstatus()

            # An event indicating that the main thread saw the process exit
            doneevent = threading.Event()

            def killerthread():
                """Wait for the timeout, then attempt to kill the related process."""
                doneevent.wait(timeout)
                try:
                    self.kill(group)
                except OSError:
                    pass
            
            # Make a thread that will kill the subprocess after waiting for the timeout.
            thd = threading.Thread(target=killerthread)
            thd.setDaemon(True)
            thd.start()

            try:
                self._waitforstatus()
            finally:
                # Set the event, so if the killer thread is still waiting, it will continue through exit
                doneevent.set()
                # Join up with the thread, which should be exiting now
                thd.join()

        return self.returncode
