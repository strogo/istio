#!/usr/bin/env python

#
# Makes a bazel workspace play nicely with standard go tools
# go build
# go test
# should work after this
#
# It does so by making symlinks from WORKSPACE/vendor to the bazel
# sandbox dirs
#
import ast
import glob
import os
import subprocess

from urlparse import urlparse

import bazel_util
import regenerate_files

THIS_DIR = os.path.dirname(os.path.abspath(__file__))

KEYS = set(["importpath", "remote", "name"])


def keywords(stmt):
    kw = {k.arg: k.value.s for k in stmt.keywords if k.arg in KEYS}
    path = kw.get("importpath", kw.get("remote"))

    u = urlparse(path)
    return u.netloc + u.path, kw["name"]

known_repos = {
        "org_golang_google": "google.golang.org",
        "com_github": "github.com",
        "org_golang": "golang.org",
        "in_gopkg": "gopkg.in"
}


# gopkg packages are of type gopkg.in/yaml.v2
# in_gopkg_yaml_v2
# com_github_hashicorp_go_multierror  --> github.com/
def repos(name):
   for r, m in known_repos.items():
       if name.startswith(r):
           rname = name[(len(r)+1):]
           fp, _, rest = rname.partition('_')
           if r == 'in_gopkg':
               return m + "/" + fp + "." + rest

           return m + "/" + fp + "/" + rest

# If we need to support more bazel functions
# add them here


class WORKSPACE(object):

    def __init__(self, external, genfiles, vendor):
        self.external = external
        self.genfiles = genfiles
        self.vendor = vendor

    # All functions should return a tuple
    # link target, source
    # target should exist
    def go_repository(self, name, path):
        return (os.path.join(self.external, name), os.path.join(self.vendor, path))

    def new_go_repository(self, name, path):
        return self.go_repository(name, path)

    def new_git_repository(self, name, path):
        return (os.path.join(self.genfiles, name), os.path.join(self.vendor, path))

    def new_git_or_local_repository(self, name, path):
        return self.new_git_repository(name, path)


def process(fl, external, genfiles, vendor):
    src = subprocess.Popen("bazel query 'kind(\"go_repository|new_git.*_repository\", \"//external:*\")' --output=build", shell=True, stdout=subprocess.PIPE).stdout.read()
    tree = ast.parse(src, fl)
    wksp = WORKSPACE(external, genfiles, vendor)
    lst = [wksp.go_repository('io_istio_api', 'istio.io/api')]

    for stmt in ast.walk(tree):
        stmttype = type(stmt)
        if stmttype == ast.Call:

            fn = getattr(wksp, stmt.func.id, "")
            if not callable(fn):
                continue

            path, name = keywords(stmt)
            if path.endswith(".git"):
                path = path[:-4]
            tup = fn(name, path)
            lst.append(tup)

    return lst


def makelink(target, linksrc):
    # make a symlink from vendor/path --> target
    try:
        os.makedirs(os.path.dirname(linksrc))
    except Exception as e1:
        if 'File exists:' not in str(e1):
            print type(e1), e1
    try:
        os.remove(linksrc)
    except Exception as e1:
        if 'Is a directory' in str(e1):
            return
        if 'No such file or directory' not in str(e1):
            print type(e1), e1
    if not os.path.exists(target):
        print target, "Does not exist"
        return
    os.symlink(target, linksrc)
    print "Linked ", linksrc, '-->', target

def bazel_to_vendor(WKSPC):
    WKSPC = bazel_util.bazel_info("workspace")
    workspace = os.path.join(WKSPC, "WORKSPACE")

    if not os.path.isfile(workspace):
        print "WORKSPACE file not found in " + WKSPC
        print "prog BAZEL_WORKSPACE_DIR"
        return -1

    vendor = os.path.join(WKSPC, "vendor")
    root = bazel_util.bazel_info("output_base")
    genfiles = bazel_util.bazel_info("bazel-genfiles")
    genfiles_external = os.path.join(genfiles, "external")
    external = os.path.join(root, "external")

    links = {target: linksrc for(target, linksrc) in process(workspace, external, genfiles_external, vendor)}

    bysrc = {}

    for (target, linksrc) in links.items():
        makelink(target, linksrc)
        print "Vendored", linksrc, '-->', target
        bysrc[linksrc] = target

    # check other directories in external
    # and symlink ones that were not covered thru workspace
    for ext_target in get_external_links(external):
        target = os.path.join(external, ext_target)
        if target in links:
            continue
        link = repos(ext_target)
        if not link:
            # print "Could not resolve", ext_target
            continue
        linksrc = os.path.join(vendor, link)

        # only make this link if we have not made it above
        if linksrc in bysrc:
            # print "Skipping ", link
            continue

        makelink(target, linksrc)
        print "Vendored", linksrc, '-->', target
    regenerate_files.regenerate(WKSPC, genfiles)

def get_external_links(external):
    return [file for file in os.listdir(external) if os.path.isdir(os.path.join(external, file))]

def main(args):
    WKSPC = bazel_util.bazel_info('workspace')
    if len(args) > 0:
        WKSPC = args[0]

    bazel_to_vendor(WKSPC)


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
