#!/usr/bin/python -t
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
# Copyright 2005 Duke University 
# Written by Seth Vidal

"""
Command line interface class and related.
"""

import os
import re
import sys
import time
import random
import logging

from optparse import OptionParser

import firmwaretools
import firmwaretools.plugins as plugins
from firmwaretools.trace_decorator import decorate, traceLog, getLog

from firmwaretools.i18n import _
import signal
import ftcommands
from firmwaretools import errors

# these are replaced by autotools when installed.
__VERSION__="unreleased_version"
SYSCONFDIR=os.path.join(os.path.dirname(os.path.realpath(sys._getframe(0).f_code.co_filename)),"..","etc")
PYTHONDIR=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])),"..")
PKGPYTHONDIR=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])),"..","firmwaretools")
PKGDATADIR=os.path.join(os.path.dirname(os.path.realpath(sys.argv[0])),"..")
CONFDIR=os.path.join(SYSCONFDIR,"firmware")
# end build system subs

def sigquit(signum, frame):
    """ SIGQUIT handler for the cli. """
    print >> sys.stderr, "Quit signal sent - exiting immediately"
    sys.exit(1)

class CliError(errors.BaseError): pass

class BaseCli(firmwaretools.FtBase):
    """This is the base class for cli.
       Inherits from FtBase """
       
    def __init__(self):
        # handle sigquit early on
        signal.signal(signal.SIGQUIT, sigquit)
        firmwaretools.FtBase.__init__(self)
        logging.basicConfig()

        self.logger = getLog()
        self.verbose_logger = getLog(prefix="verbose.")

        self.cli_commands = {}
        self.registerCommand(ftcommands.UpdateCommand())
        self.registerCommand(ftcommands.InventoryCommand())
        self.registerCommand(ftcommands.BootstrapCommand())
        self.registerCommand(ftcommands.ListPluginsCommand())

    def registerCommand(self, command):
        for name in command.getModes():
            if self.cli_commands.has_key(name):
                raise errors.ConfigError('Command "%s" already defined' % name)
            self.cli_commands[name] = command
            
    def getOptionsConfig(self, args):
        """parses command line arguments, takes cli args:
        sets up self.conf and self.cmds as well as logger objects 
        in base instance"""

        self.cmdargs = args

        self.optparser = FtOptionParser( usage='ft [options]', version=__VERSION__)
        
        # Parse only command line options that affect basic yum setup
        self.opts = self.optparser.firstParse(args)

        pluginTypes = [plugins.TYPE_CORE, plugins.TYPE_INTERACTIVE] 
        if not self.opts.fake_mode:
            pluginTypes.extend([plugins.TYPE_INVENTORY, plugins.TYPE_BOOTSTRAP])
        else:
            pluginTypes.extend([plugins.TYPE_MOCK_CORE, plugins.TYPE_MOCK_INVENTORY, plugins.TYPE_MOCK_BOOTSTRAP])

        # Read up configuration options and initialise plugins
        try:
            self._getConfig(self.opts.configFiles, 
                    pluginTypes,
                    optparser=self.optparser,
                    disabledPlugins=self.opts.disabled_plugins)
                    
        except errors.ConfigError, e:
            self.logger.critical(_('Config Error: %s'), e)
            sys.exit(1)
        except ValueError, e:
            self.logger.critical(_('Options Error: %s'), e)
            sys.exit(1)

        # subcommands can add new optparser stuff in doCheck()
        self.parseCommands()

        # Now parse the command line for real and 
        self.opts, self.args = self.optparser.parse_args(args)

        
    def parseCommands(self):
        """reads self.cmds and parses them out to make sure that the requested 
        base command + argument makes any sense at all""" 
        if not self.cli_commands.has_key(self.opts.mode):
            self.usage()
            raise CliError, "mode not specified."
    
        self.cli_commands[self.opts.mode].doCheck(self, self.opts.mode, self.cmdargs)

    def doShell(self):
        """do a shell-like interface for commands"""
        pass

    def doCommands(self):
        """
        Calls the base command passes the extended commands/args out to be
        parsed (most notably package globs).
        
        Returns a numeric result code and an optional string
           - 0 = we're done, exit
           - 1 = we've errored, exit with error string
           - 2 = we've got work yet to do, onto the next stage
        """
        
        return self.cli_commands[self.opts.mode].doCommand(self, self.opts.mode, self.args)
    

    def usage(self):
        ''' Print out command line usage '''
        self.optparser.print_help()

    def shellUsage(self):
        ''' Print out the shell usage '''
        self.optparser.print_usage()

    def updateFirmware(self):
        print
        print "Searching storage directory for available BIOS updates..."
        r = self.repo

        depFailures = {}
        def show_work(*args, **kargs):
            #print "Got callback: %s  %s" % (args, kargs)
            if kargs.get("what") == "found_package_ini":
                p = kargs.get("path")
                if len(p) > 50:
                    p = p[-50:]
                firmwaretools.pycompat.spinPrint("Checking: %s" % p)

            if kargs.get("what") == "fail_dependency_check":
                pkg = kargs.get("package")
                pkgName = "%s-%s" % (pkg.name, pkg.version)
                if pkg.conf.has_option("package", "limit_system_support"):
                    pkgName = pkgName + "-" + pkg.conf.get("package", "limit_system_support")
                kargs.get("cb")[1][pkgName] = (kargs.get("package"), kargs.get("reason"))

        updateSet = firmwaretools.repository.generateUpdateSet(r, self.yieldInventory(), cb=(show_work, depFailures) )
        print "\033[2K\033[0G"  # clear line
        needUpdate = 0
        for device in updateSet.iterDevices():
            print "Checking %s - %s" % (str(device), device.version)
            for availPkg in updateSet.iterAvailableUpdates(device):
                print "\tAvailable: %s - %s" % (availPkg.name, availPkg.version)

            pkg = updateSet.getUpdatePackageForDevice(device)
            if pkg is None:
                print "\tDid not find a newer package to install that meets all installation checks."
            else:
                print "\tFound Update: %s - %s" % (pkg.name, pkg.version)
                needUpdate = 1

        if depFailures:
            print
            print "Following packages could apply, but have dependency failures:"

        for pkg, reason in depFailures.values():
            print "\t%s - %s" % (pkg.name, pkg.version)
            print "\t\t REASON: %s" % reason

        if not needUpdate:
            print
            print "This system does not appear to have any updates available."
            print "No action necessary."
            print
            return 1
        else:
            print
            print "Found firmware which needs to be updated."
            print

        # if we get to this point, that means update is necessary.
        # any exit before this point means that there was an error, or no update
        # was necessary and should return non-zero
        if self.opts.interactive == 2:
            print
            print "Test mode complete."
            print
            return 0

        if self.opts.interactive == 1:
            print
            print "Please run the program with the '--yes' switch to enable BIOS update."
            print "   UPDATE NOT COMPLETED!"
            print
            return 0

        print "Running updates..."
        for pkg in updateSet.generateInstallationOrder():
            try:

                def statusFunc():
                    if pkg.getCapability('accurate_update_percentage'):
                        firmwaretools.pycompat.spinPrint("%s%% Installing %s - %s" % (pkg.getProgress() * 100, pkg.name, pkg.version))
                    else:
                        firmwaretools.pycompat.spinPrint("Installing %s - %s" % (pkg.name, pkg.version))
                    time.sleep(0.2)

                ret = firmwaretools.pycompat.runLongProcess(pkg.install, waitLoopFunction=statusFunc)
                print firmwaretools.pycompat.clearLine(),
                print "100%% Installing %s - %s" % (pkg.name, pkg.version)
                print "Done: %s" % pkg.getStatusStr()
                print

            except (firmwaretools.package.NoInstaller,), e:
                print "package %s - %s does not have an installer available." % (pkg.name, pkg.version)
                print "skipping this package for now."
                continue
            except (firmwaretools.package.InstallError,), e:
                print "Installation failed for package: %s - %s" % (pkg.name, pkg.version)
                print "aborting update..."
                print
                print "The error message from the low-level command was:"
                print
                print e
                break





    

from optparse import OptionParser
class FtOptionParser(OptionParser):
    """Unified cmdline option parsing and config file handling."""
    def __init__(self, *args, **kargs):
        OptionParser.__init__(self, *args, **kargs)
        
        self.add_option("--inventory", help="", action="store_const", const="inventory", dest="mode", default=None)
        self.add_option("--update", help="", action="store_const", const="update", dest="mode")
        self.add_option("--bootstrap", help="", action="store_const", const="bootstrap", dest="mode")
        self.add_option("--listplugins", action="store_const", const="listplugins", dest="mode", help="list available plugins.")


        self.add_option("-c", "--config", help="Override default config file with user-specified config file.", dest="configFiles", action="append", default=[])
        self.add_option("--extra-plugin-config", help="Add additional plugin config file.", action="append", default=[], dest="extraConfigs")
        self.add_option("-v", "--verbose", action="count", dest="verbosity", default=1, help="Display more verbose output.")
        self.add_option("-q", "--quiet", action="store_const", const=0, dest="verbosity", help="Minimize program output. Only errors and warnings are displayed.")
        self.add_option("--trace", action="store_true", dest="trace", default=False, help="Enable verbose function tracing.")
        self.add_option("--fake-mode", action="store_true", dest="fake_mode", default=False, help="Display fake data for unit-testing.")
        self.add_option("--disableplugin", action="append", dest="disabled_plugins", default=[], help="Disable single named plugin.")

        # put all 'mode' arguments here so we know early what mode we are in. 
        self.parseOptionsFirst_novalopts = [
                "--version","-q", "-v", "--quiet", "--verbose", "--trace", "--fake-mode",
                "--inventory", "--update", "--bootstrap", "--listplugins",
                ]
        self.parseOptionsFirst_valopts = ["-c", "--config", "--disableplugin", "--extra-plugin-config"]

    def firstParse(self, args):
        args = _filtercmdline(
            self.parseOptionsFirst_novalopts,
            self.parseOptionsFirst_valopts,
            args)
        opts, args = self.parse_args(args=args)

        if not opts.configFiles:
            opts.configFiles = [os.path.join(CONFDIR, "firmware.conf"), ]

        opts.configFiles = opts.configFiles + opts.extraConfigs

        return opts

def _filtercmdline(novalopts, valopts, args):
    '''Keep only specific options from the command line argument list

    This function allows us to peek at specific command line options when using
    the optparse module. This is useful when some options affect what other
    options should be available.

    @param novalopts: A sequence of options to keep that don't take an argument.
    @param valopts: A sequence of options to keep that take a single argument.
    @param args: The command line arguments to parse (as per sys.argv[:1]
    @return: A list of strings containing the filtered version of args.

    Will raise ValueError if there was a problem parsing the command line.
    '''
    out = []
    args = list(args)       # Make a copy because this func is destructive

    while len(args) > 0:
        a = args.pop(0)
        if '=' in a:
            opt, _ = a.split('=', 1)
            if opt in valopts:
                out.append(a)

        elif a in novalopts:
            out.append(a)

        elif a in valopts:
            if len(args) < 1:
                raise ValueError
            next = args.pop(0)
            if next[0] == '-':
                raise ValueError

            out.extend([a, next])

        else:
            # Check for single letter options that take a value, where the
            # value is right up against the option
            for opt in valopts:
                if len(opt) == 2 and a.startswith(opt):
                    out.append(a)

    return out