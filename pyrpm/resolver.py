#!/usr/bin/python
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Library General Public License as published by
# the Free Software Foundation; version 2 only
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Library General Public License for more details.
#
# You should have received a copy of the GNU Library General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
# Copyright 2004 Red Hat, Inc.
#
# Author: Thomas Woerner
#

import string
from hashlist import *
from rpmlist import *

def _gen_operator(flag):
    op = ""
    if flag & RPMSENSE_LESS:
        op = "<"
    if flag & RPMSENSE_GREATER:
        op += ">"
    if flag & RPMSENSE_EQUAL:
        op += "="
    return op

# ----

def _gen_depstr((name, flag, version)):
    if version == "":
        return name
    return "%s %s %s" % (name, _gen_operator(flag), version)

# ----

# normalize list
def _normalize(list):
    if len(list) < 2:
        return
    hash = { }
    i = 0
    while i < len(list):
        item = list[i]
        if hash.has_key(item):
            list.pop(i)
        else:
            hash[item] = 1
        i += 1
    return

# ----------------------------------------------------------------------------

# pre and post relations for a package
class _Relation:
    def __init__(self):
        self.pre = HashList()
        self._post = HashList()
    def __str__(self):
        return "%d %d" % (len(self.pre), len(self._post))       

# ----

# relations
class _Relations:
    def __init__(self):
        self.list = HashList()
    def __len__(self):
        return len(self.list)
    def __getitem__(self, key):
        return self.list[key]
    def append(self, pkg, pre, flag):
        if pre == pkg:
            return
        if not pkg in self.list:
            self.list[pkg] = _Relation()
        if pre not in self.list[pkg].pre:
            self.list[pkg].pre[pre] = flag
        else:
            # prefer hard requirements
            if self.list[pkg].pre[pre] == 1 and flag == 2:
                self.list[pkg].pre[pre] = flag
        for (p,f) in self.list[pkg].pre:
            if p in self.list:
                if pkg not in self.list[p]._post:
                    self.list[p]._post[pkg] = 1
            else:
                self.list[p] = _Relation()
                self.list[p]._post[pkg] = 1
    def remove(self, pkg):
        rel = self.list[pkg]
        for (r,f) in rel._post:
            if len(self.list[r].pre) > 0:
                del self.list[r].pre[pkg]
        del self.list[pkg]
    def has_key(self, key):
        return self.list.has_key(key)

# ----------------------------------------------------------------------------

class RpmResolver:
    OP_INSTALL = "install"
    OP_UPDATE = "update"
    OP_ERASE = "erase"

    def __init__(self, rpms, installed, operation):
        self.rpms = rpms
        self.operation = operation
        self.installed = installed

    # check dependencies for one rpm
    def checkPkgDependencies(self, rpm, rpmlist):
        unresolved = [ ]
        resolved = [ ]
        j = 0
        for u in rpm["requires"]:
            if u[0][0:7] == "rpmlib(": # drop rpmlib requirements
                continue
            s = rpmlist.searchDependency(u)
            if len(s) == 0: # found nothing
                unresolved.append(u)
            else: # resolved
                _normalize(s)
                resolved.append((u, s))
        return (unresolved, resolved)

    # check dependencies for a list of rpms
    def checkDependencies(self, rpmlist):
        no_unresolved = 1
        for i in xrange(len(rpmlist)):
            rlist = rpmlist[i]
            for r in rlist:
                printDebug(1, "Checking dependencies for %s" % r.getNEVRA())
                (unresolved, resolved) = self.checkPkgDependencies(r, rpmlist)
                if len(resolved) > 0 and rpmconfig.debug_level > 1:
                    # do this only in debug level > 1
                    printDebug(2, "%s: resolved dependencies:" % r.getNEVRA())
                    for (u, s) in resolved:
                        str = ""
                        for r2 in s:
                            str += "%s " % r2.getNEVRA()
                        printDebug(2, "\t%s: %s" % (_gen_depstr(u), str))
                if len(unresolved) > 0:
                    no_unresolved = 0
                    printError("%s: unresolved dependencies:" % r.getNEVRA())
                    for u in unresolved:                        
                        printError("\t%s" % _gen_depstr(u))
        return no_unresolved

    # check for conflicts in RpmList (conflicts and obsoletes)
    def checkConflicts(self, rpmlist):
        no_conflicts = 1
        for i in xrange(len(rpmlist)):
            rlist = rpmlist[i]
            for r in rlist:
                printDebug(1, "Checking for conflicts for %s" % r.getNEVRA())
                for c in r["conflicts"] + r["obsoletes"]:
                    s = rpmlist.searchDependency(c)
                    if len(s) > 0:
                        _normalize(s)
                        if r in s: s.remove(r)
                    if len(s) > 0:
                        for r2 in s:
                            printError("%s conflicts for '%s' with %s" % \
                                       (r.getNEVRA(), _gen_depstr(c), \
                                        r2.getNEVRA()))
                            no_conflicts = 0

        if no_conflicts != 1:
            return no_conflicts

        # check for file conflicts
        for f in rpmlist.filenames.multi:
            printDebug(1, "Checking for file conflicts for '%s'" % f)
            s = rpmlist.filenames.search(f)
            for j in xrange(len(s)):
                fi1 = s[j].getRpmFileInfo(f)
                for k in xrange(j+1, len(s)):
                    fi2 = s[k].getRpmFileInfo(f)
                    # ignore directories and links
                    if fi1.mode & CP_IFDIR and fi2.mode & CP_IFDIR:
                        continue
                    if fi1.mode & CP_IFLNK and fi2.mode & CP_IFLNK:
                        continue
                    # TODO: use md5
                    if fi1.mode != fi2.mode or \
                           fi1.filesize != fi2.filesize or \
                           fi1.md5 != fi2.md5:
                        no_conflicts = 0
                        printError("%s: File conflict for '%s' with %s" % \
                                   (s[j].getNEVRA(), f, s[k].getNEVRA()))
        return no_conflicts

    # return operation flag
    def operationFlag(self, flag, operation):
        f = 0
        if operation == "erase":
            if not (isInstallPreReq(flag) or \
                    not (isErasePreReq(flag) or isLegacyPreReq(flag))):
                f += 2
            if not (isInstallPreReq(flag) or \
                    (isErasePreReq(flag) or isLegacyPreReq(flag))):
                f += 1
        else: # operation: install or update
            if not (isErasePreReq(flag) or \
                    not (isInstallPreReq(flag) or isLegacyPreReq(flag))):
                f += 2
            if not (isErasePreReq(flag) or \
                    (isInstallPreReq(flag) or isLegacyPreReq(flag))):
                f += 1
        return f

    # generate relations from RpmList
    def genRelations(self, rpmlist, operation):
        relations = _Relations()

        for rlist in rpmlist:
            for r in rlist:
                printDebug(1, "Generating Relations for %s" % r.getNEVRA())
                (unresolved, resolved) = self.checkPkgDependencies(r, rpmlist)
                # ignore unresolved, we are only looking at the changes,
                # therefore not all symbols are resolvable in these changes
                for (u,s) in resolved:
                    (name, flag, version) = u
                    if name[0:7] == "config(": # drop config requirements
                        continue
                    if r in s:
                        continue
                        # drop requirements which are resolved by the package
                        # itself
                    f = self.operationFlag(flag, operation)
                    if f == 0:
                        # drop unneeded
                        continue
                    for s2 in s:
                        relations.append(r, s2, f)

        if rpmconfig.debug_level > 1:
            # print relations
            printDebug(2, "\t==== relations (%d) ====" % len(relations))
            for (pkg, rel) in relations:
                printDebug(2, "\t%d %d %s" % (len(rel.pre), len(rel._post),
                                              pkg.getNEVRA()))
            printDebug(2, "\t==== relations ====")

        return relations
    
    # generate instlist
    def genInstList(self):
        instlist = RpmList()

        for r in self.installed:
            instlist.install(r)

        for r in self.rpms:
            if self.operation == self.OP_ERASE:
                instlist.erase(r)
            elif self.operation == self.OP_UPDATE:
                instlist.update(r)
            else:
                instlist.install(r)

        return instlist

    # generate operations
    def genOperations(self, order, obsoletes):
        operations = [ ]
        if self.operation == self.OP_ERASE:
            # reverse order
            # obsoletes: there are none
            for i in xrange(len(order)-1, -1, -1):
                operations.append((self.operation, order[i]))
        else:
            for r in order:
                operations.append((self.operation, r))
                if r in obsoletes:
                    if len(obsoletes[r]) == 1:
                        operations.append((self.OP_ERASE, obsoletes[r][0]))
                    else:
                        # more than one obsolete: generate order
                        todo = RpmList()
                        for r2 in obsoletes[r]:
                            todo.install(r2)
                        relations = self.genRelations(todo, self.OP_ERASE)
                        if relations == None:                        
                            return None
                        order2 = self.orderRpms(todo, relations)
                        del relations
                        del todo
                        if order2 == None:
                            return None
                        for i in xrange(len(order2)-1, -1, -1):
                            operations.append((self.OP_ERASE, order2[i]))
                        del order2
        return operations

    # detect loop
    def detectLoop(self, relations):
        (package, rel) = relations[0]
        loop = HashList()
        loop[package] = 0
        i = 0
        pkg = package
        p = None
        while p != package and i >= 0 and i < len(relations):
            (p,f) = relations[pkg].pre[loop[pkg]]
            if p == package:
                break
            if loop.has_key(p):
                package = p
                # remove leading nodes
                while len(loop) > 0 and loop[0][0] != package:
                    del loop[loop[0][0]]
                break
            else:
                loop[p] = 0
                pkg = p
                i += 1

        if p != package:
            printError("A loop without a loop?")
            return None

        if rpmconfig.debug_level > 0:
            printDebug(1, "===== loop (%d) =====" % len(loop))
            for (p,i) in loop:
                printDebug(1, "%s" % p.getNEVRA())
            printDebug(1, "===== loop =====")

        return loop

    # breakup loop
    def breakupLoop(self, loop, relations):
        found = 0
        # first try to breakup soft loop
        for (p,i) in loop:
            (p2,f) = relations[p].pre[i]
            if f == 1:
                printDebug(1, "Removing requires for %s from %s" % \
                           (p2.getNEVRA(), p.getNEVRA()))
                del relations[p].pre[p2]
                del relations[p2]._post[p]
                found = 1
                break
        if found == 0:
            # breakup hard loop (zapping)
            (p, i) = loop[0]
            (p2,f) = relations[p].pre[i]
            printDebug(1, "Zapping requires for %s from %s to break up hard loop" % \
                       (p2.getNEVRA(), p.getNEVRA()))
            found = 1
            del relations[p].pre[p2]
            del relations[p2]._post[p]

        return found

    # order rpmlist
    def orderRpms(self, relations, no_relations):
        order = [ ]
        idx = 1
        while len(relations) > 0:
            next = None
            # we have to have at least one entry, so start with -1 for len
            next_post_len = -1
            for (pkg, rel) in relations:
                if len(rel.pre) == 0 and len(rel._post) > next_post_len:
                    next = (pkg, rel)
                    next_post_len = len(rel._post)
            if next != None:
                pkg = next[0]
                order.append(pkg)
                relations.remove(pkg)
                printDebug(2, "%d: %s" % (idx, pkg.getNEVRA()))
                idx += 1
            else:
                if rpmconfig.debug_level > 0:
                    printDebug(1, "-- LOOP --")
                    printDebug(2, "\n===== remaining packages =====")
                    for (pkg2, rel2) in relations:
                        printDebug(2, "%s" % pkg2.getNEVRA())
                        for i in xrange(len(rel2.pre)):
                            printDebug(2, "\t%s (%d)" %
                                       (rel2.pre[i][0].getNEVRA(),
                                        rel2.pre[i][1]))
                    printDebug(2, "===== remaining packages =====\n")

                # detect loop
                loop = self.detectLoop(relations)
                if loop == None:
                    return None

                # breakup loop
                if self.breakupLoop(loop, relations) != 1:
                    printError("Could not breakup loop")
                    return None

        if len(no_relations) > 0:
            printDebug(2, "===== packages without relations ====")
        for r in no_relations:
            order.append(r)
            printDebug(2, "%d: %s" % (idx, r.getNEVRA()))
            idx += 1

        return order

    # resolves list of installed, new, update and to erase rpms
    # returns ordered list of operations
    # operation has to be "install", "update" or "erase"
    def resolve(self):
        # generate instlist
        instlist = self.genInstList()

        # checking dependencies
        if self.checkDependencies(instlist) != 1:
            return None

        # check for conflicts
        if self.checkConflicts(instlist) != 1:
            return None

        # save obsolete list before freeing instlist
        obsoletes = instlist.obsoletes
        del instlist

        # generate 
        todo = RpmList()
        for r in self.rpms:
            todo.install(r)

        # resolving requires
        relations = self.genRelations(todo, self.operation)
        if relations == None:
            return None

        # save packages which have no relations
        no_relations = [ ]
        for i in xrange(len(todo)):
            rlist = todo[i]
            for r in rlist:
                if not relations.has_key(r):
                    no_relations.append(r)
        del todo

        # order package list
        order = self.orderRpms(relations, no_relations)
        if order == None:
            return None
        del relations
        del no_relations

        # generate operations
        operations = self.genOperations(order, obsoletes)
        # cleanup order list
        del order
        
        return operations