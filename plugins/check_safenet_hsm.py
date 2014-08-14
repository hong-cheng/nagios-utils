#!/usr/bin/env python
#
""" Nagios plug-in to check the health of the SafeNet Luna PCI card

The plug-in will do the following:

    * run the SafeNet lunadiag utility and check its output
    * print a message to stdout
    * exit with one of the 4 standard Nagios exit codes:
        0 = NAGIOS_OK
        1 = NAGIOS_WARNING
        2 = NAGIOS_CRITICAL
        3 = NAGIOS_UNKNOWN
        
The plug-in will attempt to run all the checks but will exit on the first critical/unknown event.
The exit on unknown can be disabled once we get to see the HSM's in action in prod and
is more comfortable with its output.

"""

import re
import sys
import commands
import os
import optparse
import time
import logging
import signal
import subprocess

__author__ = "Hong Cheng"
__maintainer__ = "Hong Cheng"

logger = logging.getLogger("check_safenet_hsm")
logger.setLevel(logging.ERROR)

#logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.basicConfig(format='%(levelname)s - %(message)s')

USAGE = """
  Usage: %prog [options]
  
  To get detailed debug output:
  
  export HSM_DEBUG=1
"""

optparser = optparse.OptionParser(usage=USAGE)

optparser.add_option("-s", "--slot", action="store", type=int, dest="slot", 
                     help="which PCI slot to test; default = 1", default=1)
optparser.add_option("-c", "--cmd", action="store", type=int, dest="cmd",
                     help="which diagnostice command to run; default = 0 (All tests)", default=0)
optparser.add_option("-d", action="store_true", dest="debug",
                     help="set loglevel to verbose, pause to see output")

HSM_DEBUG = False
(opts, args) = optparser.parse_args()
if opts.debug or os.environ.get("HSM_DEBUG", None):
    logger.setLevel(logging.DEBUG)
    logger.debug(" DEBUG is on...")
    HSM_DEBUG = True
    time.sleep(1)
    
class Alarm(Exception):
    pass
def alarm_handler(signum, frame):
    raise Alarm
signal.signal(signal.SIGALRM, alarm_handler)

class CheckHsmBase(object):

    DIAG_TOOL = "/usr/lunapci/bin/lunadiag"
    TIME_LIMIT = 3   # time limit in secs for each diagnostic command
    DISK_LIMIT_WARN = 85.0   #  disk usage warning level
    DISK_LIMIT_CRITICAL = 95.0
    
    ### nagios only deal w/ 4 levels
    NAGIOS_OK = 0
    NAGIOS_WARNING = 1
    NAGIOS_CRITICAL = 2
    NAGIOS_UNKNOWN = 3
    
    VALID_NAGIOS_RETCODES = [NAGIOS_OK, NAGIOS_WARNING, NAGIOS_CRITICAL, NAGIOS_UNKNOWN]

    ### Map diagnostic type with the command number in lunadiag
    ###
    class DiagCmd:
        DRIVER = 2
        COMM = 3
        FIRMWARE_LEVEL = 4
        PROTOCOL_LEVEL = 5
        CAPABILITIES = 6
        TOKEN_POLICIES = 7
        TSV = 8
        DUALPORT_DUMP = 9
        DUALPORT_CMD = 10
        TOKEN_INFO = 11
        MECHANISM_INFO = 12
        DEBUG_TRACE = 16

    ### map command number to ok patterns / verify methods
    luna_info = { 
            DiagCmd.DRIVER : {
                        "label" : "Driver Test",
                         "acpt_pattern": re.compile(r"drivers .+ detected")
                        },
            DiagCmd.COMM : {
                        "label" : "Communication Test",
                         "acpt_pattern": re.compile(r"Test passed")
                        },
            DiagCmd.FIRMWARE_LEVEL : {
                        "label" : "Read Firmware LevelTest",
                         "acpt_pattern": re.compile(r"Firmware: \d+.\d")
                        },
            DiagCmd.PROTOCOL_LEVEL : {
                        "label" : "Read Protocol Level Test",
                         "acpt_pattern": re.compile(r"Protocol level: \d+")
                        },
            DiagCmd.CAPABILITIES : {
                        "label" : "Read Capabilities Test",
                         "acpt_pattern": re.compile(r"lunadiag\s+version \d+")
                        },
            DiagCmd.TOKEN_POLICIES : {
                        "label" : "Read Token Policies Test",
                         "acpt_pattern": re.compile(r"lunadiag\s+version \d+")
                        },
            DiagCmd.TSV : {
                        "label" : "Read TSV Test",
                         #"acpt_pattern": re.compile(r"lunadiag\s+version \d+"),
                         "acpt_pattern": re.compile(r"Error\s+Flag\s+=\s+0\s+"),
                        },
            DiagCmd.DUALPORT_DUMP : {
                        "label" : "Read Dualport Test",
                         "acpt_pattern": re.compile(r"\w{4}: \w\w \w\w \w\w \w\w")
                        },
            DiagCmd.DUALPORT_CMD : {
                        "label" : "Read Dualport Command Test",
                         "acpt_pattern": re.compile(r"\w{4,}: \w\w \w\w \w\w \w\w")
                        },
            DiagCmd.TOKEN_INFO : { # later - need detail check, space usage, etc
                        "label" : "Token Info Test",
                        ### later - this one can have WARNING if space get to certain point
                        ### calc pct for SO and User storage space
                         "acpt_pattern": re.compile(r"Free:\s+\d{5,}"),
                         "verify": "verify_token_info"
                        },
            DiagCmd.MECHANISM_INFO : {
                        "label" : "Mechanism Info Test",
                         "acpt_pattern": re.compile(r"Test passed")
                        },
            DiagCmd.DEBUG_TRACE : {
                        "label" : "Read Debug/Trace Information Test",
                         "acpt_pattern": re.compile(r"lunadiag\s+version \d+")
                        },
        }

    def __init__(self, diag_tool=None, diag_list=[], slot=1, offset=None):
        """
        :param diag_tool: the lunadiag location, if empty, will use the global default
        :param diag_list: the list of lunadiag command numbers to be run in the lunadiag utility
                        if its empty, then run all the diags
        :param slot: which slot to test; for Luna PCI, its always slot 1
        :param offset: slot offset, unused for Luna PCI
        """
        self.diag_tool = CheckHsmBase.DIAG_TOOL
        if diag_tool:
            self.diag_tool = diag_tool
            
        logger.debug("diag_tool:[%s] " % (self.diag_tool))
        
        self.diag_list = diag_list
        if not self.diag_list:
            for k in CheckHsmBase.luna_info.keys():
                self.diag_list.append(k)
        
        logger.debug("diag_list:[%s]" % (self.diag_list))
        
        self.pre_cmd = "%s -s=%d -c=" % (self.diag_tool, slot)
        logger.debug("pre_cmd = %s" % (self.pre_cmd))
        
    def verify(self):
        """ Run the diagnostic tests and verify that the output is OK.
        :return :  CheckHsmBase.NAGIOS_OK  or  CheckHsmBase.NAGIOS_CRITICAL
        """
        for diag in self.diag_list:
            
            hsm_diag_cmd = "%s%d" % (self.pre_cmd, diag)
            logger.debug("About to run: %s" % hsm_diag_cmd)
            hsm_output = None
            hsm_error = None
            signal.alarm(CheckHsmBase.TIME_LIMIT)
            try:
                """
                status, hsm_output = commands.getstatusoutput(hsm_diag_cmd)
                """
                hsm_cmd_list = hsm_diag_cmd.split()
                logger.debug("about to call hsm cmd list:[%s]" % (hsm_cmd_list))
                p = subprocess.Popen(hsm_cmd_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                hsm_output, hsm_error = p.communicate()
                logger.debug("output from hsm:>>> %s <<<" % hsm_output)
                signal.alarm(0)
            except Alarm:
                errmsg = "%s EXCEEDED time limit of %d secs!!!" % (CheckHsmBase.luna_info[diag]["label"], 
                                                                   CheckHsmBase.TIME_LIMIT)
                logger.error(errmsg)
                try:
                    logger.debug("killing pid: %d" % (p.pid))
                    os.kill(p.pid, signal.SIGKILL)
                except OSError:
                    pass
                self.nagios_exit(errmsg, CheckHsmBase.NAGIOS_CRITICAL)
                
            logger.debug("hsm_output:[%s]  hsm_error:[%s]  " % (hsm_output, hsm_error))
            errmsg = "%s FAILED." % (CheckHsmBase.luna_info[diag]["label"])
            if hsm_error:
                self.nagios_exit(errmsg, CheckHsmBase.NAGIOS_CRITICAL)
            
            custom_verify = CheckHsmBase.luna_info[diag].get("verify", None)
            if custom_verify:
                logger.debug("Running custom verify(): %s" % custom_verify)
                custom_func = getattr(self, custom_verify)
                retcode = custom_func(hsm_output)
                if retcode != CheckHsmBase.NAGIOS_OK:
                    if retcode in CheckHsmBase.VALID_NAGIOS_RETCODES:
                        self.nagios_exit(errmsg, retcode)
                    else:
                        self.nagios_exit(errmsg, CheckHsmBase.NAGIOS_CRITICAL)
            else:
                """ just see if hsm_output has the accepted pattern """
                valid_pattern = CheckHsmBase.luna_info[diag]["acpt_pattern"]
                if not re.search(valid_pattern, hsm_output):
                    self.nagios_exit(errmsg, CheckHsmBase.NAGIOS_CRITICAL)
                    
            if HSM_DEBUG:
                time.sleep(1)
                
        return CheckHsmBase.NAGIOS_OK
    
    def verify_token_info(self, hsm_output):
        logger.debug("in verify_token_info")
        ### find storage pct remaining for SO and User, ie: 15% = WARN  5% = CRITICAL
        state = None
        space_info = {}
        for line in hsm_output.split("\n"):
            logger.debug("token info: >> %s <<" % (line))
            match_obj = re.search("(User|SO) Container Storage Info", line)
            if match_obj:
                state = match_obj.group(1)
                logger.debug(" state: %s" % state)
                continue
            if state:
                if re.search(r"^\s*$", line):
                    state = None
                    space_info = {}
                    logger.debug(" resetting state ")
                    continue
                mobj = re.search("(Total|Used):\s+(\d+)", line)
                if mobj:
                    type = mobj.group(1) 
                    space_info[type] = float(mobj.group(2))
                    logger.debug(">>> Found: %s %6.2f " % (type, space_info[type]))
                    if type == "Used":
                        pct = 100.0 * space_info["Used"] / space_info["Total"]
                        logger.debug(" ==> %6.2f %%" % (pct))
                        errmsg = "HSM %s disk usage: %6.2f exceeded threshold!!!" % (state, pct)
                        if pct >= CheckHsmBase.DISK_LIMIT_CRITICAL:
                            self.nagios_exit( errmsg, CheckHsmBase.NAGIOS_CRITICAL)
                        if pct >= CheckHsmBase.DISK_LIMIT_WARN:
                            self.nagios_exit( errmsg, CheckHsmBase.NAGIOS_WARN)
        
        return CheckHsmBase.NAGIOS_OK
                
    def nagios_exit(self, msg=None, exit_code=0):
        if msg:
            print msg
        sys.exit(exit_code)
                        
class CheckHsm(CheckHsmBase):
    pass

def main():
    """
    """
    logger.debug("Starting up, slot:[%d]  cmd:[%d]" % (opts.slot, opts.cmd))
    cho = CheckHsm()
    cho.verify()
    logger.debug("ALL OK, exiting with:[%d]" % (CheckHsm.NAGIOS_OK))
    cho.nagios_exit("All OK", CheckHsm.NAGIOS_OK)

if __name__ == "__main__":
    main()
        
