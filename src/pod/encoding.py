
import sys
import time

import sat
import ptnet
import z3

from util import *

class Base_encoding :

    SAT   = 'sat'
    UNSAT = 'unsat'
    UNDEF = 'undef'

    def __init__ (self, unfolding) :
        self.unf = unfolding
        self.__co = None

        # many algorithms in here rely on this property
        for i in range (len (self.unf.events)) :
            assert (self.unf.events[i].nr == i)
        for i in range (len (self.unf.conds)) :
            assert (self.unf.conds[i].nr == i)

    def solve (self) :
        pass
    def model (self) :
        pass

    def stats (self) :
        # nr of events, conditions, labels
        # int variables, constraints
        d = {}
        d['unf.events']         = len (self.unf.events)
        d['unf.conditions']     = len (self.unf.conds)
        d['labels.transitions'] = len (self.unf.net.trans)
        d['labels.places']      = len (self.unf.net.places)
        d['k']                  = self.k

        # distribution of events per label
        distrib = {}
        histo = {}
        s = ""
        avg = 0
        nmin = len (self.unf.net.trans[0].inverse_label)
        nmax = -1
        for t in self.unf.net.trans :
            n = len (t.inverse_label)
            distrib[t] = n
            try :
                histo[n] += 1
            except KeyError :
                histo[n] = 1
            s += "%s=%d " % (repr (t), n)

            if n < nmin : nmin = n
            if n > nmax : nmax = n
            avg += n

        avg /= len (self.unf.net.trans)

        d['labels.distrib'] = s
        d['labels.distrib.min/max/avg'] = (nmin, nmax, avg)
        d['labels.histogram'] = histo

        #if self.z3 :
        #    d['z3.constaints'] = len (self.z3.assertions())
        #if self.satf :
        #    d['sat.clauses'] = len (self.satf.clsset)
        #    d['sat.vars']    = len (self.satf.varmap)
        return d

    def ord_pair (self, x, y) :
        if x.nr < y.nr :
            return (x, y)
        else :
            return (y, x)

    def are_co (self, c1, c2) :
        self.__compute_co_relation ()
        return self.ord_pair (c1, c2) in self.__co

    def co_relation (self) :
        self.__compute_co_relation ()
        return self.__co

    def __compute_co_relation (self) :
        if self.__co != None :
            return
        self.__co = set ()
        for c in self.unf.conds :
            self.__compute_co_relation_c (c)

    def __compute_co_relation_c (self, cgoal) :
        #print "podisc: compute_co: goal", repr (cgoal)
        mpast = self.unf.new_mark ()
        mfuture = self.unf.new_mark ()

        # mark conditions consumed and events fired to mark cgoal
        work = [cgoal]
        for c in work :
            if len (c.pre) == 0 : continue
            e = sgl (c.pre)
            if e.m == mpast : continue
            e.m = mpast
            for cc in e.pre :
                cc.m = mpast
                work.append (cc)
        consumed = work
        #print "podisc: compute_co:  past"
        #print "podisc: compute_co: ", work

        # mark conditions that consume conditions in work (future of cgoal
        # or conflict)
        for c in work :
            for e in c.post :
                if e.m == mpast : continue # this one is in local config
                e.m = mfuture
                for cc in e.post :
                    cc.m = mfuture
                    work.append (cc)
        #print "podisc: compute_co:  past and future"
        #print "podisc: compute_co: ", work

        # at this point
        # - conds marked with mpast   : have been consumed to mark cgoal
        # - conds marked with mfuture : cgoal in conflict or causal # predecessor
        # - all others                : are concurrent
        l = []
        for c in self.unf.conds :
            if c.m == mpast or c.m == mfuture : continue
            if c != cgoal :
                l.append (c)
                self.__co.add (self.ord_pair (cgoal, c))
        #print "podisc: compute_co:  co"
        #print "podisc: compute_co: ", l
        #print "podisc: compute_co:  total", len (l)

class SAT_encoding (Base_encoding) :
    def __init__ (self, unfolding) :
        Base_encoding.__init__ (self, unfolding)
        self.satf = None
        self.k = -1

    def encode (self, k) :
        self.satf = sat.Cnf ()
        self.k = k

        # EQ : it is an equivalence relation
        self.__sat_encode_transitivity ()

        # IP : it preserves independence
        self.__sat_encode_labels ()
        self.__sat_encode_pre ()
        self.__sat_encode_post ()
        self.__sat_encode_co ()

        # RA : does not merge removed events
        self.__sat_encode_removal ()

        # MET : the measure of the folded net is at most k
        self.__sat_encode_measure (k)

    def __sat_encode_transitivity (self) :
        # events with events
        for ei in self.unf.events :
            for ej in self.unf.events :
                if ei == ej : continue
                for ek in self.unf.events :
                    if ek == ei or ek == ej : continue
                    vij = self.satf.var (self.ord_pair (ei, ej))
                    vjk = self.satf.var (self.ord_pair (ej, ek))
                    vik = self.satf.var (self.ord_pair (ei, ek))
                    self.satf.add ([-vij, -vjk, vik])
                    #print "podisc: sat: clause", repr (ei), repr (ej), repr (ek), [-vij, -vjk, vik]

        # conditions with conditions
        for ci in self.unf.conds :
            for cj in self.unf.conds :
                if ci == cj : continue
                for ck in self.unf.conds :
                    if ck == ci or ck == cj : continue
                    vij = self.satf.var (self.ord_pair (ci, cj))
                    vjk = self.satf.var (self.ord_pair (cj, ck))
                    vik = self.satf.var (self.ord_pair (ci, ck))
                    self.satf.add ([-vij, -vjk, vik])
                    #print "podisc: sat: clause", [-vij, -vjk, vik]

    def __sat_encode_labels (self) :
        # for each pair of events, if labels are different, they cannot be
        # merged
        for i in range (len (self.unf.events)) :
            for j in range (i + 1, len (self.unf.events)) :
                ei = self.unf.events[i]
                ej = self.unf.events[j]
                if ei.label != ej.label :
                    vij = self.satf.var (self.ord_pair (ei, ej))
                    self.satf.add ([-vij])
        
    def __sat_encode_subset (self, setx, sety) :
        # we generate a new variable v that holds iff
        # every element of setx shall be merged with at least one element
        # of sety
        #print "podisc: sat: encode_subset: setx", setx, "sety", sety
        setx = frozenset (setx)
        sety = frozenset (sety)
        v = self.satf.var (("subset", setx, sety))
        and_clause = [v]
        for x in setx :
            vx = self.satf.var (("subset_x_match", x, sety))
            and_clause.append (-vx) # conjuntion of all or variables imply v
            clause = [-v]
            for y in sety :
                vxy = self.satf.var (self.ord_pair (x, y))
                clause.append (vxy)
                self.satf.add ([-vxy, vx]) # each or implies vx
            self.satf.add (clause)
        self.satf.add (and_clause)
        return v

    def __sat_encode_pre (self) :
        # for every two events, if we decide to merge them, then the
        # presets must merge as well (the set of equivalence classes in the
        # preset of one must be equal to the set of equvalence classes in
        # the preset of the other)
        for i in range (len (self.unf.events)) :
            for j in range (i + 1, len (self.unf.events)) :
                ei = self.unf.events[i]
                ej = self.unf.events[j]
                if ei.label != ej.label : continue # optimization
                vij = self.satf.var (self.ord_pair (ei, ej))

                # subset inclusion in both directions
                v1 = self.__sat_encode_subset (ei.pre, ej.pre)
                v2 = self.__sat_encode_subset (ej.pre, ei.pre)

                #print "podisc: sat: encode_pre:", repr (ei), repr (ej), "(2 cls):"
                self.satf.add ([-vij, v1])
                self.satf.add ([-vij, v2])

    def __sat_encode_post (self) :
        # same as for __sat_encode_pre but this time for postset
        for i in range (len (self.unf.events)) :
            for j in range (i + 1, len (self.unf.events)) :
                ei = self.unf.events[i]
                ej = self.unf.events[j]
                if ei.label != ej.label : continue # optimization
                vij = self.satf.var (self.ord_pair (ei, ej))

                # subset inclusion in both directions
                v1 = self.__sat_encode_subset (ei.post, ej.post)
                v2 = self.__sat_encode_subset (ej.post, ei.post)

                #print "podisc: sat: encode_pre:", repr (ei), repr (ej), "(2 cls):"
                self.satf.add ([-vij, v1])
                self.satf.add ([-vij, v2])

    def __sat_encode_co (self) :
        self.__compute_co_relation ()
        for (c1, c2) in self.__co :
            assert ((c1, c2) == self.ord_pair (c1, c2))
            v = self.satf.var ((c1, c2))
            #print "podisc: sat: encode_co:", repr (c1), repr (c2)
            self.satf.add ([-v])

    def __sat_encode_measure (self, k) :
        # we associate an integer to every event
        bitwith = int (math.ceil (math.log (1 + len (self.unf.events), 2)))
        intmap = {}
        for e in self.unf.events :
            intmap[e] = sat.Integer (self.satf, e, bitwith)
        
        # for every two events, if they are merged, the integers must equal
        for i in range (len (self.unf.events)) :
            for j in range (i + 1, len (self.unf.events)) :
                ei = self.unf.events[i]
                ej = self.unf.events[j]
                vij = self.satf.var (self.ord_pair (ei, ej))

                intmap[ei].encode_eq (intmap[ej], vij)

        # we generate one more integer for the bound
        bound = sat.Integer (self.satf, "bound (k+1)", bitwith)
        bound.encode_eq_constant (k + 1)

        # the integer associated to any event must be smaller than the bound
        for encint in intmap.values () :
            v = encint.encode_lt (bound)
            self.satf.add ([v])

    def __sat_encode_removal (self) :
        pass

class SMT_base_encoding (Base_encoding) :
    def __init__ (self, unfolding) :
        Base_encoding.__init__ (self, unfolding)
        self.z3 = None

        # assert that the unfolding is in right shape and create the solver
        self.__smt_assert_repr ()

    def varmap (self, item) :
        return z3.Int (repr (item))
        #return z3.BitVec (repr (item), '12')

    def solve (self, timeout=-1) :
        tstr = 'timeout %ds' % (timeout / 1000) if timeout > 0 else "no timeout"
        print 'pod: bp > net: smt: solving with z3, %s ...' % tstr
        if timeout > 0 :
            if 'darwin' in sys.platform :
                self.z3.set ("soft_timeout", timeout)
            else :
                self.z3.set ("timeout", timeout)

        t1 = time.time ()
        result = self.z3.check ()
        t2 = time.time ()
        print 'pod: bp > net: smt: done, %s, %.2fs' % (result, t2 - t1)

        if result == z3.sat :
            return SMT_base_encoding.SAT
        elif result == z3.unsat :
            return SMT_base_encoding.UNSAT
        else :
            assert (result == z3.unknown)
            return SMT_base_encoding.UNDEF

    def model (self) :
        return self.z3.model ()

    def stats (self) :
        d = Base_encoding.stats (self)
        d['z3.constaints'] = len (self.z3.assertions())
        return d

    def __smt_assert_repr (self) :

        # assert that the repr() of all events and conditions is different
        reprs = set ()
        for e in self.unf.events :
            assert (repr (e) not in reprs)
            reprs.add (repr (e))
        for c in self.unf.conds :
            assert (repr (c) not in reprs)
            reprs.add (repr (c))
        for t in self.unf.net.trans :
            assert (len (t.inverse_label) != 0)
            assert (repr (t) not in reprs)
            reprs.add (repr (t))

        # not needed so far
        # for p in self.unf.net.places : assert (len (p.inverse_label) != 0)

    def encode_subset (self, setx, sety, b = None) :
        # each element of setx must be merged to some element of sety
        # this function generates and returns a boolean variable that, if it is
        # true, then subset inclusion happens

        # optimization: those elements in setx that are also in sety can be
        # omitted :)
        setx = set (setx) - sety

        l = []
        for x in setx :
            vx = self.varmap (x)
            cons = z3.Or ([vx == self.varmap (y) for y in sety])
            l.append (cons)
        if b == None :
            s = "merge-subset-%s-%s" % (repr (setx), repr (sety))
            b = z3.Bool (s)
        #print 'pod: subset: setx %s sety %s cons %s' % (setx, sety, l)
        self.z3.add (z3.Implies (b, z3.And (l)))
        return b

    def all_distinct (self, items) :
        if len (items) <= 1 : return
        #print 'pod: distinct:', items
        cons = z3.Distinct ([self.varmap (x) for x in items])
        self.z3.add (cons)

    def forbid_self_loops (self) :
        for e in self.unf.events :
            #print 'pod: forbid_self_loops:', e
            for c in e.pre :
                for cp in e.post :
                    v = self.varmap (c)
                    vp = self.varmap (cp)
                    self.z3.add (v != vp)

    def circular_subset_constraint (self, events, pre=True, post=False) :
        # encode that all presets (postsets) in events give rise to the same set
        # of equivalence classes

        print 'pod: smt: circular: %s %s %s' % (pre, post, long_list (events, 10))

        # nothing to do if there is less than 2 events
        if len (events) < 2 : return
        if (not pre) and (not post) : return

        # i's preset is a subset of i+1's preset
        for i in range (0, len (events) - 1) :
            e = events[i]
            ep = events[i + 1]
            if pre :
                self.encode_subset (e.pre, ep.pre, True)
            if post :
                self.encode_subset (e.post, ep.post, True)

        # and the last's preset is a subset of the first's
        e = events[-1]
        if pre :
            self.encode_subset (e.pre, events[0].pre, True)
        if post :
            self.encode_subset (e.post, events[0].post, True)

    def encode_non_disjoint (self, setx, sety) :
        self.z3.add (self.encode_non_disjoint_get_constraint (setx, sety))

    def encode_non_disjoint_get_constraint (self, setx, sety) :
        #print 'pod: smt: non-disjoint %s %s' % (list (setx), list (sety))
        l = []
        for x in setx :
            v = self.varmap (x)
            l.extend ([self.varmap (y) == v for y in sety])
        cons = z3.Or (l)
        #print 'pod: smt: ip: non-disjoint:', cons
        return cons

    def encode_disjoint (self, setx, sety) :
        #print 'pod: smt: disjoint %s %s' % (list (setx), list (sety))
        for x in setx :
            v = self.varmap (x)
            for y in sety :
                self.z3.add (v != self.varmap (y))
                #print 'pod: smt: ip: disjoint:', (v != self.varmap (y))

    def unf_stats (self) :
        for a in self.unf.net.trans :
            pres = [len (e.pre) for e in a.inverse_label]
            posts = [len (e.post) for e in a.inverse_label]
            pre_mi = min (pres)
            pre_ma = max (pres)
            post_mi = min (posts)
            post_ma = max (posts)
            print "pod: smt: ac '%s' count %d events  %s" % \
                    (a, len (a.inverse_label), long_list (a.inverse_label, 15))
            #print "pod:    '%s' pres %s" % (a, long_list (pres, -25))
            print "pod: smt:    '%s' pre : min,max = %d,%d" % (a, pre_mi, pre_ma)
            print "pod: smt:    '%s' post: min,max = %d,%d" % (a, post_mi, post_ma)

class SMT_encoding_sp_canonical (SMT_base_encoding) :
    def __init__ (self, unfolding) :
        SMT_base_encoding.__init__ (self, unfolding)

    def encode (self, \
            min_places=None, max_places=None, forbid_self=False,
            pre_distinct=False, merge_post=False) :

        print 'pod: bp > net: smt: sp: params: min_places       :', min_places
        print 'pod: bp > net: smt: sp: params: max_places       :', max_places
        print 'pod: bp > net: smt: sp: params: pre_distinct     :', pre_distinct
        print 'pod: bp > net: smt: sp: params: merge_post       :', merge_post
        print 'pod: bp > net: smt: sp: params: forbid_self_loops:', forbid_self

        #self.unf_stats ()
        self.z3 = z3.Solver ()
        cano_pre, cano_post = self.find_canonical_representatives ()
        self.encode_sp_canonical (cano_pre, cano_post, \
                min_places, max_places, pre_distinct, merge_post)
        if forbid_self :
            self.forbid_self_loops ()
        #print 'encoding', self.z3

    def __canonical_guy_fixed (self, nr_places=None, pre_distinct=False, merge_post=False) :
        # do the fixed encoding of the ``canonical guy'', requiesting that the
        # number of places is "nr_places", asking that presets of canonical guys
        # do not merge iff "pre_distinct" is True, and generating constraints to
        # merge also the postset if "merge_post" is True

        canonical = {}
        for a in self.unf.net.trans :
            if len (a.inverse_label) == 0 :
                continue
            if len (a.inverse_label) == 1 :
                e = next (iter (a.inverse_label))
                canonical[a] = e
                if pre_distinct:
                    self.all_distinct (e.pre)
                continue

            # for any set of events having at least two events and such that all
            # are labelled by the same label
            evs = list (a.inverse_label)

            # find the canonical representative (that one in evs that has a
            # preset of minimal size)
            m = min (range (len (evs)), key = lambda i : len (evs[i].pre))
            e = evs[m]
            canonical[a] = e

            # the variables of conditions in the preset of the canonincal's
            # preset are all different
            if pre_distinct:
                self.all_distinct (e.pre)

            # encode that all presets in the inverse_label give rise to the same
            # set of equivalence classes (possibly also for postsets)
            self.circular_subset_constraint (evs, True, merge_post)

        # print canonicals
        for e in canonical.values () : print "pod: smt: canonical:", e

        # we rely on this if there we've been requested an exact number of
        # places (if all conditions are in a preset, then they will be
        # equivalent to some canonical preset)
        if nr_places != None and not merge_post :
            for c in self.unf.conds :
                assert (len (c.post) >= 1)

        # get the list of canonical conditions ("the places")
        canonical_conds = set ()
        for e in canonical.values () : canonical_conds |= e.pre

        # all of them are >= 0; we conditionally require them to be <= nr_places
        for c in canonical_conds :
            v = self.varmap (c)
            self.z3.add (v >= 0)
            if nr_places != None :
                self.z3.add (v < nr_places)
                #print 'pod: smt: upper bound:', v < nr_places

        # for each i there is at least one canonical condition
        if nr_places != None :
            for i in range (nr_places) :
                cons = z3.Or ([i == self.varmap (c) for c in canonical_conds])
                self.z3.add (cons)
                #print 'pod: smt: lower bound:', cons

    def find_canonical_representatives (self) :
        cano_pre = {}
        cano_post = {}
        for a in self.unf.net.trans :
            evs = list (a.inverse_label)
            if (len (evs) == 0) :
                cano_pre[a] = set ()
                cano_post[a] = set ()
                continue

            # find an event with minimal preset size
            m = min (range (len (evs)), key = lambda i : len (evs[i].pre))
            cano_pre[a] = evs[m].pre
            #print 'pod: smt: canonical: action "%s" pre  %s' % (a, evs[m])

            # now one with minimal postset size
            m = min (range (len (evs)), key = lambda i : len (evs[i].post))
            cano_post[a] = evs[m].post
            #print 'pod: smt: canonical:        "%s" post %s' % (a, evs[m])

        return cano_pre, cano_post

    def encode_sp_canonical (self, cano_pre, cano_post, \
            min_places=None, max_places=None, pre_distinct=False, merge_post=False) :
        # do the fixed encoding of the ``canonical guy'', requiesting that the
        # number of places is "nr_places", asking that presets of canonical guys
        # do not merge iff "distinct" is True, and generating constraints to
        # merge also the postset if "want_post" is True

        assert (len (cano_pre) == len (cano_post) == len (self.unf.net.trans))
        for a in self.unf.net.trans :
            # encode that all presets in the inverse_label give rise to the same
            # set of equivalence classes (possibly also for postsets)
            evs = list (a.inverse_label)
            self.circular_subset_constraint (evs, True, merge_post)

            # the variables of conditions in the preset of the canonincal's
            # preset are all different (if requested)
            if pre_distinct:
                self.all_distinct (cano_pre[a])

        # FIXME
        # the next will force the number of equivalence classes to be equal to
        # nr_places, but only works if we have a canonical representative
        # condition of every class, which we only have for conditions in
        # presets; the only ones missing are maximal conditions of the
        # unfolding, it's possible to compute those classes, but I don't have
        # time :( The result is that nr_places becomes a lower bound instead of
        # the final number of classes

        # get the list of canonical conditions ("the places")
        canonical_conds = set ()
        for pre in cano_pre.values () : canonical_conds.update (pre)

        # XXX - partial fix: minimum and maximum number of conditions :)
        if merge_post and max_places != None :
            raise ValueError, "SP encoding: current encoding cannot merge postsets and set an upper bound on the number of places"

        # we rely on this if there we've been requested an exact number of
        # places (if all conditions are in a preset, then they will be
        # equivalent to some canonical preset)
        if max_places != None :
            for c in self.unf.conds :
                assert (len (c.post) >= 1)

        # all of them are >= 0; we conditionally require them to be <= nr_places
        for c in canonical_conds :
            v = self.varmap (c)
            self.z3.add (v >= 0)
            if max_places != None :
                self.z3.add (v < max_places)
                #print 'pod: smt: upper bound:', v < max_places

        # for each i there is at least one canonical condition
        if min_places != None :
            for i in range (min_places) :
                cons = z3.Or ([i == self.varmap (c) for c in canonical_conds])
                self.z3.add (cons)
                #print 'pod: smt: lower bound:', cons

class SMT_encoding_ip_canonical (SMT_encoding_sp_canonical) :
    def __init__ (self, unfolding) :
        SMT_encoding_sp_canonical.__init__ (self, unfolding)

    def encode (self, indep, \
            min_places=None, max_places=None, forbid_self=False, pre_distinct=False) :

        # merge all events with same label
        # merge the presets and postsets of two merged events
        # require preservation of independence

        print 'pod: bp > net: smt: ip: params: min_places       :', min_places
        print 'pod: bp > net: smt: ip: params: max_places       :', max_places
        print 'pod: bp > net: smt: ip: params: pre_distinct     :', pre_distinct
        print 'pod: bp > net: smt: ip: params: forbid_self_loops:', forbid_self

        #self.unf_stats ()
        self.z3 = z3.Solver ()
        cano_pre, cano_post = self.find_canonical_representatives ()
        self.encode_sp_canonical (cano_pre, cano_post, \
                min_places, max_places, pre_distinct, True)
        self.encode_ip_canonical (cano_pre, cano_post, indep)
        if forbid_self :
            self.forbid_self_loops ()

    def __encode_dependent_intersections (self, pre1, pre2, post1, post2) :

        # (pre1 \cap pre2)  is non-empty, OR
        # (pre1 \cap post2) is non-empty, OR
        # (post1 \cap pre2) is non-empty
        #print 'pod: smt: dependent_inter: pre1=%s post1=%s' % (list (pre1), list (post1))
        #print 'pod: smt:                  pre2=%s post2=%s' % (list (pre2), list (post2))

        fst_or = self.encode_non_disjoint_get_constraint (pre1, pre2)
        snd_or = self.encode_non_disjoint_get_constraint (pre1, post2)
        thrd_or = self.encode_non_disjoint_get_constraint (post1, pre2)
        cons = z3.Or ([fst_or, snd_or, thrd_or])
        self.z3.add (cons)
        #print 'pod: smt: ip: dependent:', cons

    def encode_ip_canonical (self, cano_pre, cano_post, indep) :
        nr1 = 0
        nr2 = 0
        for i in range (len (self.unf.net.trans)) :
            for j in range (i + 1, len (self.unf.net.trans)) :
                ai = self.unf.net.trans[i]
                aj = self.unf.net.trans[j]

                if indep.get (ai, aj) :
                    # independent
                    #print "pod: smt: ip: independent '%s' '%s'" % (ai, aj)
                    self.encode_disjoint (cano_pre[ai], cano_pre[aj] | cano_post[aj])
                    self.encode_disjoint (cano_post[ai], cano_pre[aj])
                    nr1 += 1
                else :
                    # dependent
                    #print "pod: smt: ip: dependent '%s' '%s'" % (ai, aj)
                    self.__encode_dependent_intersections ( \
                            cano_pre[ai], cano_pre[aj],
                            cano_post[ai], cano_post[aj])
                    nr2 += 1
        print "pod: bp > net: smt: ip: encoded pairs: dep/indep = %d/%d" % (nr2, nr1)

class SMT_base_encoding_ip (SMT_base_encoding) :
    def __init__ (self, unfolding) :
        SMT_base_encoding.__init__ (self, unfolding)
        self.k = -1

    def encode_merge_pre_post (self, which = "pre_and_post") :
        for i in range (len (self.unf.events)) :
            for j in range (i + 1, len (self.unf.events)) :
                ei = self.unf.events[i]
                ej = self.unf.events[j]
                #print "pod: smt: pre_post: ei", repr (ei), "ej", repr (ej)
                if ei.label != ej.label : continue # important optimization
                #print "pod: smt: pre_post: after!"

                xi = self.varmap (ei)
                xj = self.varmap (ej)

                s = "merge-%s-%s-%s" % (which, repr (ei), repr (ej))
                b = z3.Bool (s)
                self.z3.add (z3.Implies (xi == xj, b))
                #b = (xi == xj)

                if which in ["pre", "pre_and_post"] :
                    self.encode_subset (ei.pre, ej.pre, b)
                    self.encode_subset (ej.pre, ei.pre, b)
                if which in ["post", "pre_and_post"] :
                    self.encode_subset (ei.post, ej.post, b)
                    self.encode_subset (ej.post, ei.post, b)

    def encode_removal (self) :
        pass

class SMT_encoding_ip_1 (SMT_base_encoding_ip) :
    def __init__ (self, unfolding) :
        SMT_base_encoding_ip.__init__ (self, unfolding)

    def encode (self, k) :

        # this is the old smt_encode_1() method ;)
        self.k = k
        self.z3 = z3.Solver ()

        # equivalence: nothing to do !!

        # IP : it preserves independence
        self.__encode_labels_1 ()
        self.encode_merge_pre_post ()
        self.__smt_encode_co_1 ()

        # RA: does not merge removed events
        self.encode_removal ()

        # MET : the measure of the folded net is at most k
        self.__smt_encode_measure_1 (k)
        return

    def __encode_labels_1 (self) :
        for i in range (len (self.unf.events)) :
            for j in range (i + 1, len (self.unf.events)) :
                ei = self.unf.events[i]
                ej = self.unf.events[j]
                if ei.label != ej.label :
                    x_ei = self.varmap (ei)
                    x_ej = self.varmap (ej)
                    self.z3.add (x_ei != x_ej)

    def __smt_encode_co_1 (self) :
        self.__compute_co_relation ()
        for (c1, c2) in self.__co :
            assert ((c1, c2) == self.ord_pair (c1, c2))

            x1 = self.varmap (c1)
            x2 = self.varmap (c2)

            #print "podisc: sat: encode_co:", repr (c1), repr (c2)
            self.z3.add (x1 != x2)

    def __smt_encode_measure_1 (self, k) :
        # for each event e, x_e must be smaller or equal to k
        for e in self.unf.events :
            x = self.varmap (e)
            self.z3.add (x < k)
            self.z3.add (0 <= x)

class SMT_encoding_ip_2 (SMT_base_encoding_ip) :
    def __init__ (self, unfolding) :
        SMT_base_encoding_ip.__init__ (self, unfolding)

    def encode (self, k) :

        # this is the old smt_encode_2() method ;)
        self.k = k
        self.z3 = z3.Solver ()

        # equivalence: nothing to do !!

        # IP : it preserves independence
        print "podisc: smt_2: presets + posets"
        self.encode_merge_pre_post ()
        print "podisc: smt_2: co"
        self.__smt_encode_co_2 ()

        # RA: does not merge removed events
        #self.__smt_encode_removal_2 ()

        # MET : the measure of the folded net is at most k
        print "podisc: smt_2: measure"
        self.__smt_encode_measure_2 (k)
        print "podisc: smt_2: done"
        return

    def __smt_encode_co_2 (self) :
        self.__compute_co_relation ()
        for (c1, c2) in self.__co :
            assert ((c1, c2) == self.ord_pair (c1, c2))

            if not self.__smt_encode_co_2_need_to (c1, c2) :
                #print "podisc: smt_2: co: not needed", repr (c1), repr (c2)
                continue

            #print "podisc: smt_2: co: needed", repr (c1), repr (c2)
            x1 = self.varmap (c1)
            x2 = self.varmap (c2)

            #print "podisc: sat: encode_co:", repr (c1), repr (c2)
            self.z3.add (x1 != x2)

    def __smt_encode_co_2_need_to (self, c1, c2) :

        return True

        # FIXME this is unsound
        if len (set (e.label for e in c1.post) & set (e.label for e in c2.post)) :
            return True
        if len (set (e.label for e in c1.pre) & set (e.label for e in c2.pre)) :
            return True
        return False

    def __smt_encode_measure_2 (self, k) :
        # the number of merged transitions in each label must be under k
        self.z3.add (sum (self.varmap (t) for t in self.unf.net.trans) <= k)

        # for each label, and each event e in h' (a)
        for t in self.unf.net.trans :
            y = self.varmap (t)
            for e in t.inverse_label :
                x = self.varmap (e)
                self.z3.add (z3.And (0 <= x, x < y))

# vi:ts=4:sw=4:et:
