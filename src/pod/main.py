"""
pod [OPTIONS] COMMAND LOGFILE/PNMLFILE [DEPENFILE]

Bla bla bla

COMMAND is one of Bla
LOGFILE is the path to an XML file containing formulas (MCC 2015 format)

And OPTIONS is zero or more of the following options

 --log-first=N
   Use only the first N sequences of the log file.

 ...

pod [OPTIONS] extract-dependence    PNML
pod [OPTIONS] dump-log              LOGFILE
pod [OPTIONS] dump-pes              LOGFILE DEPENFILE
pod [OPTIONS] dump-bp               LOGFILE DEPENFILE
pod [OPTIONS] dump-encoding         LOGFILE DEPENFILE
pod [OPTIONS] dump-merge            LOGFILE DEPENFILE
pod [OPTIONS] merge                 LOGFILE DEPENFILE


OPTIONS:

--help, -h
--log-first=n
--log-only=1,2,4
--log-exclude=7,23
--output=PATH

"""

try :
    from util import *

    import os
    import sys
    import resource
    import networkx
    import argparse

    import z3
    import ptnet
    import pes

    from log import *
    from folding import *
    from equivalence import *
    from transformations import *
except ImportError, e:
    error_missing_package (e)

if sys.version_info < (2, 7, 0) or sys.version_info >= (3, 0, 0) :
    print ("")
    print ("*** ERROR ***")
    print ("This tool relies on Python 2.7!!")
    print ("Install Python 2.7 or modify the first line of the file 'po-discovery.py' so that it calls Python 2.7")
    print ("")
    sys.exit (1)

class Main :
    def __init__ (self) :

        self.arg_command = ""
        self.arg_log_path = ""
        self.arg_depen_path = ""

        self.arg_log_first = -1
        self.arg_log_only = []
        self.arg_log_exclude = []
        self.arg_log_negative = ""

        self.arg_output_path = ""
        self.arg_eq = "id"

        self.acset = None
        self.log = None
        self.log_negative = None
        self.indep = None
        self.pes = None
        self.meq = None
        self.bp = None
        self.net = None

    def parse_cmdline_args (self) :

        cmd_choices = [
                "extract-dependence",
                "dump-log",
                "dump-pes",
                "dump-bp",
                "dump-encoding",
                "dump-merge",
                "merge",
                ]
        eq_choices = [
                "id",
                "sp-all",
                "sp-pre-sgl",
                ]
        #p = argparse.ArgumentParser (usage = __doc__, add_help=False)
        p = argparse.ArgumentParser (usage=__doc__)
        #p.add_argument ("-h", "--help", action="store_true")
        p.add_argument ("--log-first", type=int)
        p.add_argument ("--log-only")
        p.add_argument ("--log-negative")
        p.add_argument ("--log-exclude")
        p.add_argument ("--output")
        p.add_argument ("--eq", choices=eq_choices, default="id")
        #p.add_argument ("--format", choices=["pdf","dot","pnml"])

        p.add_argument ('cmd', metavar="COMMAND", choices=cmd_choices)
        p.add_argument ('log_pnml', metavar="LOGFILE/PNML")
        p.add_argument ('depen', metavar="DEPENFILE", nargs="?", default=None)

        args = p.parse_args ()
        print "pod: args:", args

        #if args.help :
        #    print __doc__
        #    sys.exit (0);

        self.arg_command = args.cmd
        self.arg_depen_path = args.depen
        self.arg_eq = args.eq
        self.arg_log_path = args.log_pnml
        self.arg_log_first = args.log_first
        self.arg_log_negative = args.log_negative

        if self.arg_command not in ["extract-dependence", "dump-log"] :
            if self.arg_depen_path == None :
                raise Exception, "Expected path to a dependence file"

        if args.log_only != None :
            try :
                self.arg_log_only = [int (x) for x in args.log_only.split (",")]
            except Exception :
                raise Exception, "'%s': expected a comma-separated list of numbers" % (args.log_only)
        if args.log_exclude != None :
            try :
                self.arg_log_exclude = [int (x) for x in args.log_exclude.split (",")]
            except Exception :
                raise Exception, "'%s': expected a comma-separated list of numbers" % (args.log_exclude)

        if args.output != None :
            self.arg_output_path = args.output
        else :
            d = {
                "extract-dependence" : "dependence.txt",
                "dump-pes"           : "pes.pdf",
                "dump-bp"            : "bp.pdf",
                "dump-encoding"      : "encoding.smt2",
                "merge"              : "output.pnml"}
            self.arg_output_path = d.get (self.arg_command, "output.txt")
        for opt in [
                    "arg_command",
                    "arg_depen_path",
                    "arg_log_path",
                    "arg_log_first",
                    "arg_log_only",
                    "arg_log_exclude",
                    "arg_log_negative",
                    "arg_output_path",
                    "arg_eq",
                    ] :
            output_pair (sys.stdout, opt, self.__dict__[opt], 16, "pod: args: ")

    def main (self) :
        self.parse_cmdline_args ()

        if self.arg_command == "extract-dependence" :
            self.cmd_extract_dependence ()
        elif self.arg_command == "merge" :
            self.cmd_merge ()
        else :
            print 'pod: command not yet implemented'

    def cmd_extract_dependence (self) :

        # load the net
        net = load_net (self.arg_log_path, "pnml", "pod: extract: ")

        # create a dependence relation and fill it from the net
        dep = Depen ()
        print "pod: extract: extracting dependence relation ..."
        dep.from_net_names (net)

        # XXX - hack: ensure that the relation is "positively" stored
        assert (dep.negate == False)
        print "pod: extract: done, %d different actions, %d pairs" \
                % (len (dep.domain), len (dep.pairs))

        # warnings
        s = set ()
        for t in net.trans :
            if " " in t.name :
                print "pod: extract: WARNING: transition '%s' contains spaces in the name" % t.name
            if t.name in s :
                print "pod: extract: WARNING: 2 transition with same name: '%s'" % t.name
            s.add (t.name)

        # save
        try :
            f = open (self.arg_output_path, "w")
            f.write ("# Dependence relation on transition names, automatically extracted from:\n")
            f.write ("# %s\n" % self.arg_log_path)
            for (a1, a2) in dep.pairs :
                f.write ("%s %s\n" % (a1.name, a2.name))
            f.close ()
        except Exception as (e, m) :
            raise Exception, "'%s': %s" % (self.arg_output_path, m)
        print "pod: extract: output saved to '%s'" % self.arg_output_path

    def cmd_dump_log (self) :
        raise NotImplementedError

    def cmd_merge (self) :

        # load the positive and negative logs
        self.__load_all_logs ()

        # load the independence relation
        self.__load_indep ()

        # build the PES
        print "pod: building the PES from the logs..."
        self.pes = log_to_pes (self.log_both, self.indep)

        #print 'indep', self.indep
        #print 'es', es
        #print 'log positive', repr (self.log)
        #print 'log negative', repr (self.log_negative)
        #print 'log both', repr (self.log_both)

        # build the BP
        print "pod: building the BP from the PES..."
        self.bp = pes_to_bp (self.pes, self.indep)

        # merge the BP into a net
        self.__merge ()

        # save the net
        f = open (self.arg_output_path, "w")
        self.net.write (f, 'pnml')
        f.close ()
        #try :
        #except Exception as (e, m) :
        #    raise Exception, "'%s': %s" % (self.arg_output_path, m)
        print "pod: net saved to '%s'" % self.arg_output_path

    def __load_all_logs (self) :
        # create a new action set
        self.acset = ActionSet ()

        # load the positive log
        print "pod: loading log with positive information"
        self.log = self.__load_log (self.arg_log_path, \
                "pod: positive: ")
        #self.log.traces = self.log.traces[:2]

        # create another log to store positive and negative information and
        # set its actionset to the be the same as the positive log, so all
        # the three logs will share the same ActionSet
        self.log_both = self.log.clone ()
        self.log_both.actionset = self.acset

        # load negative and fill log_both
        if self.arg_log_negative != None :
            print "pod: loading log with negative information"
            self.log_negative = self.__load_log (self.arg_log_negative, \
                    "pod: negative: ")
            self.log_both.union (self.log_negative)

    def __load_log (self, path, prefix="pod: ") :
        log = Log (self.acset)
        try :
            size = os.path.getsize (path) / (1024 * 1024.0)
            print "%sloading log file '%s' (%.1fM), assuming XES format" % (prefix, path, size)
            f = open (path, 'r')
            log.read (f, 'xes')
            f.close ()
        except Exception as (e, m) :
            raise Exception, "'%s': %s" % (path, m)
        nre = sum (len (seq) for seq in log.traces)
        print '%sdone, %d logs, %d log events, %d distinct actions' \
                % (prefix, len (log.traces), nre, len (self.acset))
        return log

    def __load_indep (self) :

        # load the file arg_depen_path into a Depen object, we share the
        # same ActionSet than all the three logs
        dep = Depen (self.acset)
        try :
            print "pod: loading dependence from file '%s'" % self.arg_depen_path
            f = open (self.arg_depen_path, 'r')
            i = 0
            for line in f :
                i += 1
                line = line.lstrip ()
                if len (line) == 0 : continue
                if line[0] == '#' : continue
                ls = line.split ()
                if len (ls) != 2 :
                    raise Exception, "line %d: expected two words separated by spaces"
                a1 = self.acset.lookup (ls[0])
                if a1 == None :
                    print "pod: line %d: NOTICE: new action '%s' not happening in the logs" % (i, ls[0])
                    a1 = self.acset.lookup_or_create (ls[0])
                a2 = self.acset.lookup (ls[1])
                if a2 == None :
                    print "pod: line %d: NOTICE: new action '%s' not happening in the logs" % (i, ls[1])
                    a2 = self.acset.lookup_or_create (ls[1])
                dep.set (a1, a2)
            f.close ()
        except Exception as (e, m) :
            raise Exception, "'%s': %s" % (self.arg_depen_path, m)
        print 'pod: done, %d pairs, %d distinct actions now known' \
                % (len (dep), len (self.acset))

        print 'pod: validating reflexivity'
        try :
            dep.check_is_dependence ()
        except Exception as e:
            print 'pod: ERROR: %s' % e
            print "pod: are you sure '%s' is a dependence relation for '%s'?" \
                    % (self.arg_depen_path, self.arg_log_path)
            raise e
        self.indep = Indep ()
        self.indep.from_depen (dep)

    def __merge (self) :

        # construir el encoding
        # pasarselo a z3
        # construir la equivalencia
        # fusionar

        print "pod: folding the BP into a net"
        print "pod: bp > net: using equivalence '%s'" % self.arg_eq

        # selecting the folding equivalence
        if self.arg_eq == "id" :
            domain = set (self.bp.events) | set (self.bp.conds)
            self.meq = IdentityMergingEquivalence (domain)
        elif self.arg_eq == "sp-all" :
            self.meq = SpMergingEquivalenceFactory.one_place (self.bp)
        elif self.arg_eq == "sp-pre-sgl" :
            self.meq = SpMergingEquivalenceFactory.pre_singleton (self.bp)
        else :
            raise AssertionError, "Internal inconsistency"

        # the merge equivalence is meq, folding the BP into a net
        (net, e2t, c2p) = bp_to_net (self.bp, self.meq)
        self.net = net

        # verify transformations
        print 'pod: bp > net: asserting correctness of made transformations...'
        bp_to_net_assert_sp (self.bp, self.meq, e2t, c2p)


# vi:ts=4:sw=4:et:
