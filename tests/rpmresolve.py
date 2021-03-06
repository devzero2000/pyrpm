#!/usr/bin/python
#
# rpmresolve
#
# list dependency tree
#
# (c) 2004 Thomas Woerner <twoerner@redhat.com>
#
# version 2005-03-09-01
#

import sys, os, time

PYRPMDIR = ".."
if not PYRPMDIR in sys.path:
    sys.path.append(PYRPMDIR)
import pyrpm
import pyrpm.database.memorydb

def usage():
    print """Usage: %s [-v[v]] {-i|-U|-r} [--installed <dir>]
                       [<rpm name/package>...]

  -h  | --help                print help
  -v  | --verbose             be verbose, and more, ..
  -E  | --ignore-epoch        ignore epoch in provides and requires
  -i                          install packages
  -e                          erase packages
  -R                          no resolve call
  -r                          show detailed requires for packages
  -f                          file conflict check
  -c                          check installed
  -O                          no operation list output
  -d <dir>                    load files from dir
  --installed <dir>           directory with installed rpms

""" % sys.argv[0]

# ----------------------------------------------------------------------------

sout =  os.readlink("/proc/self/fd/1")
devpts = 0
if sout[0:9] == "/dev/pts/":
    devpts = 1

def progress_write(msg):
    if devpts == 1:
        sys.stdout.write("\r")
    sys.stdout.write(msg)
    if devpts == 0:
        sys.stdout.write("\n")
    sys.stdout.flush()

# ----------------------------------------------------------------------------

def main():
    rpms = [ ]
    ignore_epoch = 0
    verbose = 0
    installed_dir = None
    installed = [ ]
    dir = None
    resolve = 1
    output_op = 1
    requires = 0

#    if len(sys.argv) == 1:
#        usage()
#        sys.exit(0)

    pyrpm.rpmconfig.nofileconflicts = 1
    pyrpm.rpmconfig.checkinstalled = 0
    ops = [ ]
    i = 1
    op = pyrpm.OP_UPDATE
    while i < len(sys.argv):
        if sys.argv[i] == "-h" or sys.argv[i] == "--help":
            usage()
            sys.exit(0)
        elif sys.argv[i][:2] == "-v":
            j = 1
            while j < len(sys.argv[i]) and sys.argv[i][j] == "v":
                verbose += 1
                j += 1
        elif sys.argv[i] == "--verbose":
            verbose += 1
        elif sys.argv[i] == "-i":
            op = pyrpm.OP_INSTALL
        elif sys.argv[i] == "-F":
            op = pyrpm.OP_FRESHEN
        elif sys.argv[i] == "-e":
            op = pyrpm.OP_ERASE
        elif sys.argv[i] == "-f":
            pyrpm.rpmconfig.nofileconflicts = 0
        elif sys.argv[i] == "-c":
            pyrpm.rpmconfig.checkinstalled = 1
        elif sys.argv[i] == "-R":
            resolve = 0
        elif sys.argv[i] == "-r":
            requires = 1
        elif sys.argv[i] == "-O":
            output_op = 0
        elif sys.argv[i] == "-E"or sys.argv[i] == "--ignore-epoch":
            ignore_epoch = 1
        elif sys.argv[i] == "--installed":
            i += 1
            installed_dir = sys.argv[i]+"/"
        elif sys.argv[i] == "-d":
            i += 1
            dir = sys.argv[i]
        else:
            ops.append((op, sys.argv[i]))
        i += 1

    pyrpm.rpmconfig.debug = verbose
    pyrpm.rpmconfig.warning = verbose
    pyrpm.rpmconfig.verbose = verbose

    if dir:
        if not os.path.exists(dir) or not os.path.isdir(dir):
            print "%s does not exists or is not a directory." % dir
            sys.exit(1)
        print "Loading rpm packages from %s" % dir
        list = os.listdir(dir)
        list.sort
        for entry in list:
            if not entry or not entry[-4:] == ".rpm":
                continue
            n = dir+"/"+entry
            if not os.path.isfile(n):
                continue
            ops.append((op, n))

    # -- load installed

    if installed_dir != None:
        list = os.listdir(installed_dir)
        for i in xrange(len(list)):
            f = list[i]
            if verbose > 0:
                progress_write("Loading installed [%d/%d] " % (i+1, len(list)))

            r = pyrpm.RpmPackage(pyrpm.rpmconfig, "%s%s" % (installed_dir, f))
            try:
                r.read(tags=pyrpm.rpmconfig.resolvertags)
                r.close()
            except Exception, msg:
                print msg
                print "Loading of %s%s failed, ignoring." % (installed_dir, f)
                continue
            installed.append(r)

        if verbose > 0 and len(list) > 0:
            print
            del list

    if len(ops) == 0 and len(installed) == 0 and \
           pyrpm.rpmconfig.checkinstalled == 0:
        usage()
        sys.exit(0)

    if len(ops) > 0:
        print "==============================================================="
        print "Loading Packages"
        # -- load install/update/erase

        i = 1
        _ops = [ ]
        for op, f in ops:
            if verbose > 0:
                progress_write("Reading %d/%d " % (i, len(ops)))
            r = pyrpm.RpmPackage(pyrpm.rpmconfig, f)
            try:
                r.read(tags=pyrpm.rpmconfig.resolvertags)
                r.close()
            except Exception, msg:
                print msg
                print "Loading of %s failed, exiting." % f
                sys.exit(-1)
            _ops.append((op, r))
            i += 1
        if verbose > 0 and len(ops) > 0:
            print
        ops = _ops

    print "==============================================================="
    print "Feeding resolver"

    db = pyrpm.database.memorydb.RpmMemoryDB(pyrpm.rpmconfig, None)
    db.addPkgs(installed)
    resolver = pyrpm.RpmResolver(pyrpm.rpmconfig, db)
    del db

    if len(ops) > 0:
        print "Adding new packages"
    i = 1
    l = len(ops)
    for op, r in ops:
        if verbose > 0:
            progress_write("Feeding %d/%d " % (i, len(ops)))
        if op == pyrpm.OP_INSTALL:
            ret = resolver.install(r)
        elif op == pyrpm.OP_UPDATE:
            ret = resolver.update(r)
        elif op == pyrpm.OP_FRESHEN:
            ret = resolver.freshen(r)
        else: # op == pyrpm.OP_ERASE
            ret = resolver.erase(r)
        if ret != pyrpm.RpmResolver.OK and \
               ret != pyrpm.RpmResolver.ALREADY_ADDED and \
               ret != pyrpm.RpmResolver.ALREADY_INSTALLED:
            if ret == pyrpm.RpmResolver.OLD_PACKAGE:
                print "old package: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.NOT_INSTALLED:
                print "not installed: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.UPDATE_FAILED:
                print "update failed: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.ARCH_INCOMPAT:
                print "arch incompat: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.OBSOLETE_FAILED:
                print "obsolete failed: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.CONFLICT:
                print "conflict: %s" % r.getNEVRA()
            elif ret == pyrpm.RpmResolver.FILE_CONFLICT:
                print "file conflicts: %s" % r.getNEVRA()
            else:
                print ret
        i += 1
    if verbose > 0 and len(ops) > 0:
        print
    del ops

    cl = time.time()
    unresolved = resolver.getUnresolvedDependencies()
    print "resolver.getUnresolvedDependencies(): time=%f" % (time.time() - cl)
    if len(unresolved) > 0:
        print "- Unresolved dependencies -------------------------------------"
    for pkg in unresolved:
        print "  %s" % pkg.getNEVRA()
        for dep in unresolved[pkg]:
            print "\t%s" % pyrpm.depString(dep)

    conflicts = resolver.getConflicts()
    if len(conflicts) > 0:
        print "- Conflicts ---------------------------------------------------"
    for pkg in conflicts:
        print "  %s" % pkg.getNEVRA()
        for (dep,rpm) in conflicts[pkg]:
            print "\t%s: %s" % (pyrpm.depString(dep), rpm.getNEVRA())

    if pyrpm.rpmconfig.nofileconflicts == 0:
        fconflicts = resolver.getFileConflicts()
        if len(fconflicts) > 0:
            print "- File Conflicts ----------------------------------------------"
        for pkg in fconflicts:
            print "  %s" % pkg.getNEVRA()
            for (f,p) in fconflicts[pkg]:
                print "\t%s: %s" % (f, p.getNEVRA())

    if resolve == 1:
        print "==============================================================="
        print "Resolving"
        if resolver.resolve() != 1:
            sys.exit(-1)

    if len(resolver.installs) > 0:
        print "- Installs ----------------------------------------------------"
        for pkg in resolver.installs:
            print "  %s" % pkg.getNEVRA()
    if len(resolver.updates) > 0:
        print "- Updates -----------------------------------------------------"
        for pkg in resolver.updates:
            print "  %s" % pkg.getNEVRA()
            for p in resolver.updates[pkg]:
                print "\t%s" % p.getNEVRA()
    if len(resolver.obsoletes) > 0:
        print "- Obsoletes ---------------------------------------------------"
        for pkg in resolver.obsoletes:
            print "  %s" % pkg.getNEVRA()
            for p in resolver.obsoletes[pkg]:
                print "\t%s" % p.getNEVRA()
    if len(resolver.erases) > 0:
        print "- Erases ------------------------------------------------------"
        for pkg in resolver.erases:
            print "  %s" % pkg.getNEVRA()
        print "---------------------------------------------------------------"

    if requires:
        print "==============================================================="
        print "Requires - '*' marks prereqs"
        if pyrpm.rpmconfig.checkinstalled == 1:
            list = resolver.getDatabase().getPkgs()
        else:
            list = resolver.installs
        for pkg in list:
            for dep in pkg["requires"]:
                reqs = [ ]
                if pyrpm.isLegacyPreReq(dep[1]):
                    reqs.append("legacy")
                if pyrpm.isInstallPreReq(dep[1]):
                    reqs.append("install")
                if pyrpm.isErasePreReq(dep[1]):
                    reqs.append("erase")
                if len(reqs) > 0:
                    print "  %s: '%s' *%s*" % (pkg.getNEVRA(),
                                               pyrpm.depString(dep),
                                               " ".join(reqs))
                else:
                    print "  %s: '%s'" % (pkg.getNEVRA(), pyrpm.depString(dep))
        print "==============================================================="

    installs = resolver.installs
    updates = resolver.updates
    obsoletes = resolver.obsoletes
    erases = resolver.erases
    del resolver

    print "==============================================================="
    print "Ordering"
    orderer = pyrpm.RpmOrderer(pyrpm.rpmconfig, installs, updates, obsoletes,
                               erases)

    cl = time.time()
    operations = orderer.order()
    print "orderer.order(): time=%f" % (time.time() - cl)

    del orderer

    if operations == None:
        sys.exit(-1)

    if output_op:
        for op,pkg in operations:
            print op, pkg.source

    sys.exit(0)

if __name__ == '__main__':
    hotshot = 0
    if hotshot:
        import tempfile
        from hotshot import Profile
        import hotshot.stats
        filename = tempfile.mktemp()
        prof = Profile(filename)
        try:
            prof = prof.runcall(main)
        except SystemExit:
            pass
        prof.close()
        del prof
        s = hotshot.stats.load(filename)
        s.strip_dirs().sort_stats('time').print_stats(20)
        s.strip_dirs().sort_stats('cumulative').print_stats(20)
        os.unlink(filename)
    else:
        main()
